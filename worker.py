import queue
import threading
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Carga opcional de .env (producción/distribución)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)
except ImportError:  # pragma: no cover
    pass

from core.ai_engine import AIEngine
from core.media_io import (
    ensure_readable_for_whisper,
    is_media_extension,
)
from core.social_media import build_social_report
from core.transcriber import Transcriber
from main import (
    _safe_write_json,
    _safe_write_text,
    _setup_logger,
    build_report,
    get_project_root,
    load_settings,
    prepare_job_folder,
    record_job,
)


class ProcessingWorker(threading.Thread):
    """Hilo que transcribe un archivo y genera contenido para TODAS las redes sociales.

    Genera:
      - Transcripción Whisper (raw + formateada)
      - Metadatos YouTube (legacy, para compatibilidad)
      - Bundle multi-plataforma (YouTube/IG/TikTok/X/FB/LI) habilitadas
      - Informe TXT unificado + JSON completo
    """

    def __init__(
        self,
        media_path: Path,
        message_queue: queue.Queue,
        settings: dict | None = None,
        daemon: bool = True,
        generate_all_social: bool = True,
    ):
        super().__init__(daemon=daemon)
        self.media_path = media_path
        self.message_queue = message_queue
        self.settings = settings or load_settings()
        self.generate_all_social = generate_all_social

    def _send(self, msg_type: str, data=None):
        self.message_queue.put({"type": msg_type, "data": data})

    def run(self):
        project_root = Path(__file__).resolve().parent
        output_folder = project_root / self.settings.get("paths", {}).get("output", "output")
        logger = _setup_logger(output_folder)
        job_folder: Path | None = None
        try:
            if not is_media_extension(self.media_path):
                raise ValueError(f"Formato de archivo no soportado: {self.media_path.suffix}")

            output_folder.mkdir(parents=True, exist_ok=True)

            models_cfg = self.settings.get("models", {})
            whisper_cfg = models_cfg.get("whisper", {})
            transcription_cfg = self.settings.get("transcription", {})
            language = transcription_cfg.get("language") or whisper_cfg.get("language", "es")
            model_size = transcription_cfg.get("model_size") or whisper_cfg.get("name", "base")

            self._send("status", "Comprobando códec multimedia (media_io / FFmpeg)...")
            temp_folder = get_project_root() / self.settings.get("paths", {}).get("temp", ".tmp")
            preflight = ensure_readable_for_whisper(self.media_path, temp_folder=temp_folder)
            for w in preflight.warnings:
                self._send("warning", f"[media_io] {w}")
            media_to_transcribe = preflight.ready_path
            if preflight.used_transcode:
                self._send(
                    "status",
                    f"Pre-convertido a WAV por códec no estándar ({self.media_path.suffix})",
                )

            self._send("status", "Cargando modelo de transcripción...")
            self._send("progress", 0.1)
            transcriber = Transcriber(model_name=model_size)

            self._send("status", "Transcribiendo audio con Whisper...")
            self._send("progress", 0.3)
            transcription = transcriber.transcribe(
                media_to_transcribe,
                language=language,
                prompt=transcriber.prompt_from_filename(self.media_path.name),
            )
            transcript_for_ai = transcriber.format_for_ai(transcription)

            self._send("status", "Conectando motor IA multi-proveedor...")
            self._send("progress", 0.5)
            ai = AIEngine()
            logger.info(
                "Worker: AIEngine listo. provider.default=%s | available=%s",
                ai.ai_cfg.get("default_provider"),
                ai.available_providers(),
            )

            # Bundle social media (la parte NUEVA profesional)
            social_bundle = None
            if self.generate_all_social:
                try:
                    self._send(
                        "status",
                        "Generando contenido para redes sociales (YouTube/IG/TikTok/X/FB/LI)...",
                    )
                    self._send("progress", 0.65)
                    social_bundle = ai.generate_social_media_bundle(
                        transcript_for_ai,
                        filename=self.media_path.name,
                        settings=self.settings,
                    )
                    logger.info(
                        "Worker: Social bundle OK. Plataformas=%s. Errores=%s.",
                        social_bundle.enabled_platforms(),
                        list(social_bundle.errors.keys()),
                    )
                except Exception as social_exc:
                    logger.warning(
                        "Worker: falló la generación social; continúa con YouTube legacy. %s",
                        social_exc,
                    )
                    self._send("warning", f"Redes sociales: {social_exc}")

            # Legacy YouTube metadata (compatibilidad hacia atrás)
            self._send("status", "Generando metadatos YouTube (legacy)...")
            self._send("progress", 0.8)
            youtube_data = ai.generate_youtube_metadata(
                transcript_for_ai, filename=self.media_path.name
            )

            self._send("status", "Guardando resultados...")
            self._send("progress", 0.9)
            job_folder = prepare_job_folder(
                output_folder, self.media_path.stem, self.media_path.stem
            )

            report = build_report(youtube_data)
            _safe_write_text(job_folder / "resultado_youtube.txt", report)
            _safe_write_text(job_folder / "transcripcion.txt", report)
            _safe_write_text(
                job_folder / "transcripcion_raw.txt",
                transcription.get("text", ""),
            )

            # NUEVO: bundle social media profesional
            payload: dict = {
                "archivo": str(self.media_path.resolve()),
                "transcripcion": transcription,
                "youtube_legacy": youtube_data,
                "config": {
                    "whisper_model": transcription.get("model"),
                    "ai_default_provider": ai.ai_cfg.get("default_provider"),
                    "ai_available_providers": ai.available_providers(),
                    "social_media_status": ai.social_media_status(self.settings),
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
                self.media_path,
                job_folder,
                status="completado",
                logger=logger,
            )

            self._send("status", "¡Completado!")
            self._send("progress", 1.0)
            self._send(
                "done",
                {
                    "job_folder": str(job_folder),
                    "redes_sociales": social_bundle.enabled_platforms() if social_bundle else [],
                    "errores_redes": social_bundle.errors if social_bundle else {},
                },
            )
        except Exception as exc:
            tb = traceback.format_exc()
            short_error = f"{type(exc).__name__}: {exc}"
            logger.error("Worker falló en %s:\n%s", self.media_path, tb)
            try:
                output_folder.mkdir(parents=True, exist_ok=True)
                record_job(
                    output_folder,
                    self.media_path,
                    job_folder,
                    status="error",
                    error_msg=short_error,
                    logger=logger,
                )
            except Exception:
                pass
            self._send(
                "error",
                {
                    "message": (
                        f"{short_error}\n\n" f"Revisa el log: {output_folder / 'error.log'}"
                    ),
                    "traceback": tb,
                },
            )
