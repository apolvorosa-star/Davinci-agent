import json
import logging
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Carga opcional de .env (producción / distribución)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)
except ImportError:  # pragma: no cover
    pass

from core.ai_engine import AIEngine
from core.social_media import build_social_report
from core.transcriber import Transcriber
from core.media_io import (
    ensure_readable_for_whisper,
    ffmpeg_available,
    is_media_extension,
    media_extensions,
)
from main import (
    _safe_write_json,
    _safe_write_text,
    _setup_logger,
    build_report,
    find_media_files,
    get_project_root,
    load_settings,
    prepare_job_folder,
    process_media,
    record_job,
)


def load_processed(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return set(data.get("processed", []))
    except (json.JSONDecodeError, OSError):
        return set()
    return set()


def save_processed(log_path: Path, processed: set[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(
                {"processed": sorted(processed)},
                f,
                indent=2,
                ensure_ascii=False,
            )
    except OSError:
        pass


def process_media_full(
    media_path: Path,
    output_folder: Path,
    settings: dict,
    transcriber: Transcriber,
    ai: AIEngine,
    logger: logging.Logger,
) -> Path:
    """Procesamiento completo: transcribe + YouTube legacy + bundle social media."""
    output_folder.mkdir(parents=True, exist_ok=True)
    job_folder: Path | None = None
    try:
        models_cfg = settings.get("models", {}) or {}
        whisper_cfg = models_cfg.get("whisper", {}) or {}
        transcription_cfg = settings.get("transcription", {}) or {}
        language = transcription_cfg.get("language") or whisper_cfg.get("language", "es")

        # PRE-FLIGHT: extension + códec / transcodificar si hace falta
        if not is_media_extension(media_path):
            logger.warning(
                "Watcher: extensión '%s' no estándar; se intenta de todos modos.",
                media_path.suffix,
            )
        tf = get_project_root() / settings.get("paths", {}).get("temp", ".tmp")
        preflight = ensure_readable_for_whisper(media_path, temp_folder=tf)
        for w in preflight.warnings:
            logger.warning("[media_io Watcher] %s", w)
        media_to_transcribe = preflight.ready_path
        if preflight.used_transcode:
            logger.info(
                "Watcher: transcodificado %s a WAV por códec no estándar.",
                media_path.name,
            )

        prompt_ctx = transcriber.prompt_from_filename(media_path.name)
        transcription = transcriber.transcribe(media_to_transcribe, language=language, prompt=prompt_ctx)
        transcript_ai = transcriber.format_for_ai(transcription)

        logger.info("Watcher: transcripción OK (%d chars)", len(transcription.get("text", "")))

        # 1) Bundle profesional multi-plataforma (el NUEVO pipeline)
        social_bundle = None
        try:
            logger.info("Watcher: generando bundle social media...")
            social_bundle = ai.generate_social_media_bundle(
                transcript_ai,
                filename=media_path.name,
                settings=settings,
            )
            logger.info(
                "Watcher: social bundle OK. Plataformas=%s | Errores=%s",
                social_bundle.enabled_platforms(),
                list(social_bundle.errors.keys()),
            )
        except Exception as social_exc:  # noqa: BLE001
            logger.warning(
                "Watcher: fallo social bundle (continuamos con legacy): %s", social_exc
            )

        # 2) Legacy YouTube (compatibilidad)
        youtube_data = ai.generate_youtube_metadata(transcript_ai, filename=media_path.name)

        job_folder = prepare_job_folder(output_folder, media_path.stem, media_path.stem)

        report = build_report(youtube_data)
        _safe_write_text(job_folder / "resultado_youtube.txt", report)
        _safe_write_text(job_folder / "transcripcion.txt", report)
        _safe_write_text(job_folder / "transcripcion_raw.txt", transcription.get("text", ""))

        payload = {
            "archivo": str(media_path.resolve()),
            "transcripcion": transcription,
            "youtube_legacy": youtube_data,
            "config": {
                "whisper_model": transcription.get("model"),
                "ai_default_provider": ai.ai_cfg.get("default_provider"),
                "ai_available_providers": ai.available_providers(),
                "social_media_status": ai.social_media_status(settings),
            },
        }
        if social_bundle is not None:
            payload["social_media"] = social_bundle.to_dict()
            try:
                reporte_social = build_social_report(social_bundle)
                _safe_write_text(job_folder / "redes_sociales.txt", reporte_social)
            except Exception:
                pass

        _safe_write_json(job_folder / "resultado_youtube.json", payload)
        _safe_write_json(job_folder / "contenido_redes_sociales.json", payload)

        record_job(
            output_folder,
            media_path,
            job_folder,
            status="completado",
            logger=logger,
        )
        return job_folder
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("Watcher: error procesando %s:\n%s", media_path, tb)
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


def watch() -> None:
    settings = load_settings()
    project_root = Path(__file__).resolve().parent
    paths_cfg = settings.get("paths", {}) or {}
    input_folder = project_root / paths_cfg.get("input", "input")
    output_folder = project_root / paths_cfg.get("output", "output")
    input_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    logger = _setup_logger(output_folder)

    processed_log = output_folder / ".processed.json"
    processed = load_processed(processed_log)

    models_cfg = settings.get("models", {}) or {}
    whisper_cfg = models_cfg.get("whisper", {}) or {}
    transcription_cfg = settings.get("transcription", {}) or {}
    model_size = transcription_cfg.get("model_size") or whisper_cfg.get("name", "base")
    transcriber = Transcriber(model_name=model_size)
    ai = AIEngine()

    logger.info(
        "Watcher iniciado. AI: default_provider=%s available=%s",
        ai.ai_cfg.get("default_provider"),
        ai.available_providers(),
    )
    try:
        status = ai.social_media_status(settings)
        logger.info(
            "Watcher: plataformas sociales habilitadas = %s",
            status.get("available_platforms", []),
        )
    except Exception as exc:
        logger.warning("Watcher: no se pudo consultar status social (%s)", exc)

    interval = (settings.get("watcher", {}) or {}).get("interval_seconds", 10)

    print(
        f"👀 Vigilando {input_folder} cada {interval}s...\n"
        f"🤖 Proveedor IA por defecto: [{ai.ai_cfg.get('default_provider')}] "
        f"modelo={ai.model} | disponibles: {', '.join(ai.available_providers()) or '(ninguno)'}\n"
        f"📲 Redes sociales habilitadas: "
        + (
            ", ".join(
                getattr(ai.social_media_status(settings), "get", lambda k, d=None: d)(
                    "available_platforms", []
                )
            )
            or "(consultar settings.yaml)"
        )
        + "\n"
    )
    while True:
        for media_path in find_media_files(input_folder):
            media_key = str(media_path.resolve())
            if media_key in processed:
                continue
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{ts}] ✨ Nuevo archivo detectado: {media_path.name}")
            logger.info("Watcher: detectado nuevo archivo %s", media_path)
            try:
                process_media_full(
                    media_path, output_folder, settings, transcriber, ai, logger=logger
                )
                processed.add(media_key)
                save_processed(processed_log, processed)
                print(f"[{ts}] ✅ OK procesado: {media_path.name}")
            except Exception as exc:
                short = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "Watcher: error procesando %s: %s", media_path, short
                )
                print(f"[{ts}] ❌ ERROR {media_path.name}: {short}")
        time.sleep(interval)


if __name__ == "__main__":
    watch()
