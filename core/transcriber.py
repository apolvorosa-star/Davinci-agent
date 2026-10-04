import os
import re
import shutil
from pathlib import Path
from typing import Union

try:
    import whisper
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Falta la librería 'openai-whisper'. Instálala con: pip install openai-whisper"
    ) from exc


# Extensiones soportadas por Whisper (incluye formatos que requieren ffmpeg)
WHISPER_SUPPORTED_EXTS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aac",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".mpeg", ".mpg", ".3gp", ".m4v",
}


class Transcriber:
    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        try:
            self.model = whisper.load_model(model_name)
        except Exception as exc:
            raise RuntimeError(
                f"No se pudo cargar el modelo Whisper '{model_name}'. "
                f"Error: {type(exc).__name__}: {exc}. "
                "Comprueba la conexión a internet para la descarga inicial, "
                "el espacio libre en disco y que CUDA/CPU sean compatibles."
            ) from exc

    def transcribe(
        self,
        audio_path: Union[str, Path],
        language: str = "es",
        prompt: str | None = None,
    ) -> dict:
        """Transcribe un archivo de audio/video usando Whisper.

        Args:
            audio_path: Ruta al archivo multimedia.
            language: Código de idioma (por defecto 'es').
            prompt: Texto de contexto para guiar la transcripción (p. ej. título/canción).

        Returns:
            Diccionario con el texto completo y los segmentos con timestamps.

        Raises:
            FileNotFoundError: Si el archivo no existe.
            ValueError: Si la extensión no está soportada o el archivo está vacío.
            RuntimeError: Si falta ffmpeg o la transcripción falla internamente.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {audio_path}")

        suffix = audio_path.suffix.lower()
        if suffix not in WHISPER_SUPPORTED_EXTS:
            raise ValueError(
                f"Extensión no soportada por Whisper: {suffix}. "
                f"Extensiones válidas: {sorted(WHISPER_SUPPORTED_EXTS)}"
            )

        try:
            file_size = audio_path.stat().st_size
        except OSError as exc:
            raise RuntimeError(
                f"No se pudo leer el archivo {audio_path.name}: {exc}"
            ) from exc
        if file_size == 0:
            raise ValueError(f"El archivo está vacío: {audio_path}")

        # Para formatos no-WAV/MP3 comprueba que exista ffmpeg (lo necesita Whisper)
        if suffix not in {".wav", ".mp3"} and shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "Falta 'ffmpeg' en el PATH. Instálalo y reinicia la terminal: "
                "https://www.gyan.dev/ffmpeg/builds/ (Windows) o `winget install ffmpeg`."
            )

        # Contexto para karaoke/canciones: idioma y, si se proporciona, título/artista
        initial_prompt = prompt or f"Transcripción en español."

        try:
            result = self.model.transcribe(
                str(audio_path),
                language=language,
                initial_prompt=initial_prompt,
                temperature=0,
                condition_on_previous_text=False,
                verbose=False,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Error en la transcripción de {audio_path.name}: "
                f"{type(exc).__name__}: {exc}."
            ) from exc

        raw_text = result.get("text", "").strip()
        segments = result.get("segments", [])
        if not raw_text and not segments:
            # Caso: audio silencioso o sin voz detectable. No es un fallo grave,
            # pero lo indicamos explícitamente para que la IA no genere metadatos vacíos.
            raw_text = (
                "[No se detectó voz o contenido transcribible en el audio.]"
            )

        return {
            "text": raw_text,
            "language": result.get("language") or language,
            "model": self.model_name,
            "segments": [
                {
                    "start": round(float(segment["start"]), 2),
                    "end": round(float(segment["end"]), 2),
                    "text": str(segment["text"]).strip(),
                }
                for segment in segments
            ],
        }

    def format_for_ai(self, transcription: dict) -> str:
        """Prepara la transcripción con timestamps para ser procesada por la IA."""
        lines = ["Transcripción con marcas de tiempo:"]
        for segment in transcription.get("segments", []):
            start = self._format_time(segment["start"])
            end = self._format_time(segment["end"])
            lines.append(f"[{start} -> {end}] {segment['text']}")
        return "\n".join(lines)

    @staticmethod
    def prompt_from_filename(filename: str) -> str:
        """Genera un prompt de contexto a partir del nombre del archivo multimedia."""
        from pathlib import Path

        stem = Path(filename).stem
        # Intenta extraer Artista - Título
        if " - " in stem:
            parts = stem.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            # Quita sufijos comunes de karaoke entre paréntesis
            title = re.sub(r"\s*\([^)]*karaoke[^)]*\)", "", title, flags=re.IGNORECASE).strip()
            artist = re.sub(r"^\d+\s*[-.\\s]\s*", "", artist).strip()
            return f"Letra de la canción '{title}' por {artist}."

        return f"Contenido del vídeo/audio: {stem}."

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Convierte segundos a formato HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
