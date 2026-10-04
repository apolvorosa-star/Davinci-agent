from __future__ import annotations

import json
import logging
import os
import re
import sys
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml

from core.media_io import (
    MEDIA_EXTENSIONS as _EXT,
)
from core.media_io import (
    ensure_readable_for_whisper,
    is_media_extension,
)

MEDIA_EXTENSIONS = set(_EXT)


_PROJECT_ROOT_CACHE: Path | None = None


def get_project_root() -> Path:
    global _PROJECT_ROOT_CACHE
    if _PROJECT_ROOT_CACHE is not None:
        return _PROJECT_ROOT_CACHE
    candidates = [
        Path(__file__).resolve().parent,
        Path(sys.path[0]).resolve() if sys.path and sys.path[0] else None,
        Path.cwd().resolve(),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        for marker in ("settings.yaml", "config", "requirements.txt"):
            if (candidate / marker).exists() or (candidate / "config" / marker).exists():
                _PROJECT_ROOT_CACHE = candidate
                return candidate
    _PROJECT_ROOT_CACHE = Path(__file__).resolve().parent
    return _PROJECT_ROOT_CACHE


def load_settings(config_path: str | Path | None = None) -> dict[str, Any]:
    root = get_project_root()
    if config_path is None:
        # Configuración personal (no se distribuye) tiene prioridad sobre la plantilla
        user_cfg = root / "config" / "settings.user.yaml"
        config_path = user_cfg if user_cfg.exists() else root / "config" / "settings.yaml"
    config_path = Path(config_path)
    default_cfg: dict[str, Any] = {
        "app": {"name": "DaVinci Agent", "version": "0.3.0"},
        "paths": {"input": "./input", "output": "./output", "temp": "./.tmp"},
        "models": {"whisper": {"name": "base", "language": "es"}},
        "parameters": {"chunk_duration": 30, "max_context": 4096},
        "watcher": {"interval_seconds": 10},
    }
    if not config_path.exists():
        return default_cfg
    try:
        with open(config_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError("settings.yaml debe contener un diccionario raíz")
        merged: dict[str, Any] = dict(default_cfg)
        for k, v in loaded.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        return merged
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(
            f"[WARN] No se pudo cargar {config_path.name}: {exc}. Usando defaults.", file=sys.stderr
        )
        return default_cfg


def _setup_logger(output_folder: str | Path, level: int = logging.INFO) -> logging.Logger:
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("davinci_agent")
    logger.setLevel(level)
    if logger.handlers:
        return logger
    log_file = output_folder / "error.log"
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def _safe_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _safe_write_json(path: str | Path, data: Any, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _safe_write_text(path, serialized, encoding=encoding)


def prepare_job_folder(
    output_root: str | Path,
    base_name: str,
    subfolder_hint: str = "",
    max_attempts: int = 1000,
) -> Path:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    clean = re.sub(r"[^\w\s\-().]", "_", base_name).strip() or "job"
    if subfolder_hint:
        clean = f"{clean}_{subfolder_hint}"
    candidate = output_root / clean
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    for n in range(2, max_attempts + 1):
        candidate = output_root / f"{clean}_{n}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    raise RuntimeError(
        f"No se pudo crear carpeta única para '{base_name}' tras {max_attempts} intentos."
    )


def build_report(youtube_data: dict[str, Any]) -> str:
    titulo = youtube_data.get("titulo", "").strip()
    descripcion = youtube_data.get("descripcion", "").strip()
    capitulos = youtube_data.get("capitulos", []) or []
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("METADATOS GENERADOS PARA YOUTUBE")
    lines.append(f"Generado: {datetime.now(UTC).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("-- TÍTULO -----------------------------------------------------------")
    lines.append(titulo or "(vacío)")
    lines.append("")
    lines.append("-- DESCRIPCIÓN ------------------------------------------------------")
    lines.append(descripcion or "(vacía)")
    lines.append("")
    lines.append("-- CAPÍTULOS --------------------------------------------------------")
    if capitulos:
        for cap in capitulos:
            inicio = cap.get("inicio", "") if isinstance(cap, dict) else ""
            tit = cap.get("titulo", "") if isinstance(cap, dict) else str(cap)
            lines.append(f"  {inicio:<12} {tit}")
    else:
        lines.append("  (sin capítulos)")
    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def record_job(
    output_folder: str | Path,
    media_path: str | Path,
    job_folder: str | Path | None,
    status: str = "pendiente",
    error_msg: str | None = None,
    logger: logging.Logger | None = None,
) -> None:
    output_folder = Path(output_folder)
    media_path = Path(media_path)
    jobs_file = output_folder / "jobs.json"
    try:
        if jobs_file.exists():
            with open(jobs_file, encoding="utf-8") as f:
                jobs = json.load(f)
            if not isinstance(jobs, list):
                jobs = []
        else:
            jobs = []
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "archivo": str(media_path.resolve()),
            "nombre": media_path.name,
            "status": status,
            "job_folder": str(job_folder.resolve()) if job_folder else None,
        }
        if error_msg:
            entry["error"] = error_msg
        jobs.append(entry)
        _safe_write_json(jobs_file, jobs)
    except Exception as exc:
        if logger:
            logger.warning("No se pudo registrar el job: %s", exc)
        else:
            print(f"[WARN] No se pudo registrar el job: {exc}", file=sys.stderr)


def find_media_files(folder: str | Path, recursive: bool = True) -> list[Path]:
    folder = Path(folder)
    if not folder.exists():
        return []
    iterator: Iterable[Path] = folder.rglob("*") if recursive else folder.glob("*")
    files: list[Path] = []
    for p in iterator:
        try:
            if p.is_file() and is_media_extension(p):
                files.append(p)
        except OSError:
            continue
    files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0)
    return files


def process_media(
    media_path: str | Path,
    output_folder: str | Path,
    settings: dict[str, Any] | None = None,
    transcriber: Any | None = None,
    ai: Any | None = None,
    logger: logging.Logger | None = None,
) -> Path:
    media_path = Path(media_path)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    settings = settings or load_settings()
    if logger is None:
        logger = _setup_logger(output_folder)
    if not media_path.exists():
        raise FileNotFoundError(f"No existe: {media_path}")
    if not is_media_extension(media_path):
        # Si la extensión no está en la lista, lo advertimos PERO seguimos
        # (podría ser un formato nuevo soportado directamente por Whisper/FFmpeg)
        logger.warning(
            "Extensión '%s' no en lista de confianza. Se intentará procesar igualmente.",
            media_path.suffix,
        )
    else:
        # En la lista soportada
        pass

    # ---- PRE-FLIGHT: ensure Whisper-readable (preconvierte códecs raros con FFmpeg)
    temp_media: Path | None = None
    temp_result = ensure_readable_for_whisper(
        media_path, temp_folder=get_project_root() / settings.get("paths", {}).get("temp", ".tmp")
    )
    if temp_result.warnings:
        for w in temp_result.warnings:
            logger.warning("[media_io] %s", w)
    if temp_result.used_transcode:
        temp_media = temp_result.ready_path
        media_to_transcribe = temp_media
        logger.info(
            "Pre-conversión FFmpeg aplicada a '%s' (códec no standard). WAV listo: %s",
            media_path.name,
            temp_media.name,
        )
    else:
        media_to_transcribe = temp_result.ready_path

    job_folder: Path | None = None
    try:
        from core.ai_engine import AIEngine
        from core.transcriber import Transcriber

        models_cfg = settings.get("models", {}) or {}
        whisper_cfg = models_cfg.get("whisper", {}) or {}
        transcription_cfg = settings.get("transcription", {}) or {}
        language = transcription_cfg.get("language") or whisper_cfg.get("language", "es")
        model_size = transcription_cfg.get("model_size") or whisper_cfg.get("name", "base")

        if transcriber is None:
            transcriber = Transcriber(model_name=model_size)

        prompt_ctx = transcriber.prompt_from_filename(media_path.name)
        transcription = transcriber.transcribe(
            media_to_transcribe, language=language, prompt=prompt_ctx
        )
        transcript_ai = transcriber.format_for_ai(transcription)

        if ai is None:
            ai = AIEngine()

        youtube_data = ai.generate_youtube_metadata(transcript_ai, filename=media_path.name)

        job_folder = prepare_job_folder(output_folder, media_path.stem, media_path.stem)
        report = build_report(youtube_data)
        _safe_write_text(job_folder / "resultado_youtube.txt", report)
        _safe_write_json(
            job_folder / "resultado_youtube.json",
            {
                "archivo": str(media_path.resolve()),
                "transcripcion": transcription,
                "youtube": youtube_data,
                "config": {
                    "whisper_model": transcription.get("model"),
                    "ai_default_provider": getattr(ai, "ai_cfg", {}).get("default_provider"),
                    "ai_available_providers": getattr(ai, "available_providers", list)(),
                },
            },
        )
        _safe_write_text(job_folder / "transcripcion.txt", report)
        _safe_write_text(job_folder / "transcripcion_raw.txt", transcription.get("text", ""))

        record_job(
            output_folder,
            media_path,
            job_folder,
            status="completado",
            logger=logger,
        )
        return job_folder
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Error procesando %s:\n%s", media_path, tb)
        try:
            record_job(
                output_folder,
                media_path,
                job_folder,
                status="error",
                error_msg=f"{type(exc).__name__}: {exc}",
                logger=logger,
            )
        except Exception:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="DaVinci Agent — Transcribe audio y genera metadatos para redes sociales."
    )
    parser.add_argument("media", nargs="?", type=Path, help="Archivo multimedia a procesar")
    parser.add_argument("-o", "--output", type=Path, help="Carpeta de salida")
    parser.add_argument("-w", "--watch", action="store_true", help="Activa el modo watcher")
    parser.add_argument(
        "--list", action="store_true", help="Lista los archivos multimedia en ./input"
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    project_root = get_project_root()
    paths_cfg = settings.get("paths", {}) or {}
    output_folder = (
        Path(args.output) if args.output else (project_root / paths_cfg.get("output", "output"))
    )
    output_folder.mkdir(parents=True, exist_ok=True)
    logger = _setup_logger(output_folder)

    if args.list:
        input_folder = project_root / paths_cfg.get("input", "input")
        files = find_media_files(input_folder)
        if not files:
            print(f"No hay archivos multimedia en {input_folder}")
        else:
            print(f"Encontrados {len(files)} archivos en {input_folder}:")
            for f in files:
                print(f"  - {f.name}")
        return 0

    if args.watch:
        from watcher import watch

        watch()
        return 0

    if args.media:
        try:
            job = process_media(args.media, output_folder, settings, logger=logger)
            print(f"OK procesado: {job}")
            return 0
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
