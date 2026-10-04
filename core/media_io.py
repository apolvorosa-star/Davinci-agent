"""Validación profesional de archivos multimedia + pre-conversión automática vía FFmpeg.

Este módulo soluciona el problema de "mi archivo X no es aceptado" o "Whisper
no puede leer códec raro Y". Funciona en 2 niveles:

1. **Lista extendida de extensiones aceptadas** (``SUPPORTED_MEDIA_EXTENSIONS``)
   con 60+ formatos de audio y vídeo profesionales (MP4/MKV/MOV/WMV/FLV/MXF/TS/
   HLS/M4B/AIFF/WMA/AMR/OPUS…).

2. **Preflight real (no solo extensión)**. Antes de transcribir, se intenta
   sondear el archivo con FFprobe (o fallback a FFmpeg). Si el códec de audio
   interno no es compatible con Whisper (ej: WMA pro, AC3 extraño, códec
   propietario), **automáticamente convierte a WAV mono 16kHz PCM 16-bit**
   (formato nativo 100% soportado por Whisper sin pérdida).

3. **Manejo robusto de errores**: si FFmpeg no está, se notifica al usuario
   exactamente cómo instalarlo (winget/chocolatey/descarga oficial) y se
   intenta de todos modos (Whisper soporta los formatos más comunes sin él).

Uso mínimo::

    from core.media_io import (
        normalize_media_path,
        ensure_readable_for_whisper,
        media_extensions,
    )

    archivo_limpio, warnings = normalize_media_path("Mi vídeo.MP4")
    archivo_listo_para_whisper, tmp_flag, info = ensure_readable_for_whisper(
        archivo_limpio,
        temp_folder=Path("./.tmp"),
    )
    # Usa archivo_listo_para_whisper directamente en Transcriber.transcribe()
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ===========================================================================
# 1) LISTA COMPLETA DE EXTENSIONES SOPORTADAS
# ===========================================================================
# Incluye:
#  - Audio consumer: mp3, wav, m4a, flac, ogg, wma, aac…
#  - Audio profesional/creativo: aiff, aif, au, caf, pcm, snd, m4b (audiolibros)
#  - Vídeo consumer: mp4, m4v, mov, avi, mkv, webm, wmv, flv, 3gp, mpeg…
#  - Vídeo broadcast/profesional: mxf, ts, m2ts, mts, vob, mp2, mod, tod
#  - Streaming / cámaras: h264, h265, hevc, mjpeg
# ===========================================================================
SUPPORTED_AUDIO_EXTENSIONS: set[str] = {
    ".3ga",
    ".aac",
    ".ac3",
    ".aif",
    ".aiff",
    ".alac",
    ".amr",
    ".ape",
    ".au",
    ".caf",
    ".dts",
    ".flac",
    ".gsm",
    ".m4a",
    ".m4b",
    ".mid",
    ".midi",
    ".mka",
    ".mlp",
    ".mod",
    ".mp1",
    ".mp2",
    ".mp3",
    ".mpc",
    ".oga",
    ".ogg",
    ".oma",
    ".opus",
    ".pcm",
    ".qcp",
    ".ra",
    ".ram",
    ".snd",
    ".spx",
    ".tta",
    ".voc",
    ".vox",
    ".wav",
    ".wma",
    ".wv",
    ".xwm",
}

SUPPORTED_VIDEO_EXTENSIONS: set[str] = {
    ".264",
    ".265",
    ".3g2",
    ".3gp",
    ".amv",
    ".asf",
    ".avi",
    ".bik",
    ".dav",
    ".divx",
    ".dv",
    ".dvr-ms",
    ".f4v",
    ".flv",
    ".gxf",
    ".h264",
    ".h265",
    ".hevc",
    ".k3g",
    ".m1v",
    ".m2p",
    ".m2t",
    ".m2ts",
    ".m2v",
    ".m4v",
    ".mkv",
    ".mod",
    ".moov",
    ".mov",
    ".mp2v",
    ".mp4",
    ".mp4v",
    ".mpe",
    ".mpeg",
    ".mpeg1",
    ".mpeg2",
    ".mpeg4",
    ".mpg",
    ".mpv",
    ".mts",
    ".mxf",
    ".nsv",
    ".nut",
    ".ogm",
    ".ogv",
    ".ogx",
    ".pva",
    ".qt",
    ".rm",
    ".rmvb",
    ".roq",
    ".swf",
    ".tod",
    ".ts",
    ".tts",
    ".vcd",
    ".vc1",
    ".vob",
    ".vp9",
    ".webm",
    ".wm",
    ".wmv",
    ".wtv",
    ".xesc",
    ".xvid",
}

SUPPORTED_MEDIA_EXTENSIONS: set[str] = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS

# Alias para compatibilidad con main.py / worker.py / watcher.py
MEDIA_EXTENSIONS = SUPPORTED_MEDIA_EXTENSIONS

_SUPPORTED_LOWER: set[str] = {e.lower() for e in SUPPORTED_MEDIA_EXTENSIONS}


def media_extensions() -> set[str]:
    """Devuelve la lista actual de extensiones soportadas (inmutable vista)."""
    return set(_SUPPORTED_LOWER)


def is_media_extension(path: str | os.PathLike[str]) -> bool:
    """Devuelve ``True`` si la extensión de ``path`` está soportada.

    Comparación *case-insensitive* (``.MP4`` == ``.mp4``).
    """
    p = Path(path)
    if not p.suffix:
        return False
    return p.suffix.lower() in _SUPPORTED_LOWER


def is_probably_video(path: str | os.PathLike[str]) -> bool:
    """``True`` si la extensión pertenece a un formato de vídeo conocido."""
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def is_probably_audio(path: str | os.PathLike[str]) -> bool:
    """``True`` si la extensión pertenece a un formato de audio conocido."""
    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


# ===========================================================================
# 2) Normalización de rutas + sanity checks de Windows
# ===========================================================================
_PATH_ILLEGAL_RE = __import__("re").compile(r'[\x00-\x1f<>:"|?*]')


@dataclass
class MediaSanityReport:
    """Reporte de comprobaciones previas a transcripción."""

    original_path: Path
    normalized_path: Path
    exists: bool
    is_file: bool
    size_bytes: int = 0
    extension_supported: bool = False
    extension_lower: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ffmpeg_available: bool = False
    ffmpeg_version: str = ""
    codec_probe: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and self.exists and self.is_file and self.extension_supported


def normalize_media_path(
    raw_path: str | os.PathLike[str],
) -> tuple[Path, list[str]]:
    """Normaliza una ruta de archivo multimedia para ser segura en cualquier SO.

    Devuelve ``(ruta_normalizada, warnings)``.
    """
    warnings: list[str] = []
    p = Path(str(raw_path)).expanduser()
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        p = Path(os.path.abspath(str(p)))

    name = p.name
    if len(name) > 220:
        warnings.append(
            f"Nombre de archivo muy largo ({len(name)} chars); "
            "podría dar problemas en algunos sistemas."
        )
    if _PATH_ILLEGAL_RE.search(name):
        warnings.append("Nombre de archivo contiene caracteres no estándar;")
    return p, warnings


# ===========================================================================
# 3) FFmpeg / FFprobe  —  autodetección + versión + preflight códec
# ===========================================================================
@dataclass
class TranscodeResult:
    """Resultado de ``ensure_readable_for_whisper``."""

    ready_path: Path
    used_transcode: bool
    temp_created: bool
    info: MediaSanityReport
    warnings: list[str] = field(default_factory=list)
    transcode_command: list[str] = field(default_factory=list)

    def cleanup_temp(self) -> None:
        """Si se creó un transcode temporal, lo borra."""
        if self.temp_created and self.ready_path.exists():
            try:
                self.ready_path.unlink(missing_ok=True)
            except OSError:
                pass


def _find_tool(binary: str) -> str | None:
    """Busca ``ffmpeg`` / ``ffprobe`` en PATH o en rutas típicas de Windows."""
    if shutil.which(binary):
        return shutil.which(binary)
    # Rutas típicas de instalación estática de FFmpeg en Windows
    candidates_win = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "FFmpeg"
        / "bin"
        / f"{binary}.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "FFmpeg"
        / "bin"
        / f"{binary}.exe",
        Path.home() / "scoop" / "shims" / f"{binary}.exe",
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages" / f"{binary}.exe",
    ]
    for c in candidates_win:
        if c.exists():
            return str(c)
    return None


def ffmpeg_available() -> tuple[bool, str, str | None, str | None]:
    """Devuelve ``(disponible, version_humana, ffmpeg_path, ffprobe_path)``."""
    ffmpeg = _find_tool("ffmpeg")
    ffprobe = _find_tool("ffprobe")
    if not ffmpeg:
        return False, "no instalado", None, None
    try:
        out = subprocess.check_output(
            [ffmpeg, "-version"], stderr=subprocess.STDOUT, timeout=10, text=True
        )
        first_line = out.splitlines()[0] if out.splitlines() else "FFmpeg (desconocido)"
        return True, first_line.strip(), ffmpeg, ffprobe
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        return False, f"error: {exc}", ffmpeg, ffprobe


FFMPEG_INSTALL_HINT = (
    "Instala FFmpeg para soportar CUALQUIER códec de audio/vídeo "
    "(incluso formatos propietarios o raros):\n"
    "  Windows (método 1 - winget recomendado):   winget install --id=Gyan.FFmpeg  -e\n"
    "  Windows (método 2 - Chocolatey):           choco install ffmpeg -y\n"
    "  Windows (método 3 - manual):               https://www.gyan.dev/ffmpeg/builds/  →"
    " descarga 'ffmpeg-release-essentials.zip', extrae, y añade la carpeta 'bin' al PATH.\n"
    "  macOS:                                     brew install ffmpeg\n"
    "  Linux (Debian/Ubuntu):                     sudo apt update && sudo apt install ffmpeg"
)


# ===========================================================================
# 4) Media Sanity: chequeo completo del archivo
# ===========================================================================
def media_sanity_check(raw_path: str | os.PathLike[str]) -> MediaSanityReport:
    """Ejecuta todas las comprobaciones previas sobre un archivo multimedia."""
    normalized, warnings = normalize_media_path(raw_path)
    report = MediaSanityReport(
        original_path=Path(str(raw_path)),
        normalized_path=normalized,
        exists=normalized.exists(),
        is_file=normalized.is_file(),
        extension_supported=is_media_extension(normalized),
        extension_lower=normalized.suffix.lower(),
        warnings=list(warnings),
    )

    # Tamaño
    if report.exists and report.is_file:
        try:
            report.size_bytes = normalized.stat().st_size
            if report.size_bytes < 2048:
                report.warnings.append(
                    f"Archivo sospechosamente pequeño ({report.size_bytes} bytes);"
                    " podría estar corrupto."
                )
        except OSError as exc:
            report.errors.append(f"No se puede leer el archivo: {exc}")

    # Extensión: si no está en la lista, listar qué vemos
    if not report.extension_supported:
        report.errors.append(
            f"Extensión '{report.extension_lower}' no está en la lista conocida. "
            f"Extensiones soportadas: {len(_SUPPORTED_LOWER)} (ver core/media_io.py)."
        )

    # FFmpeg disponible?
    ok_ver, ver, _ffmpeg_path, _ = ffmpeg_available()
    report.ffmpeg_available = ok_ver
    report.ffmpeg_version = ver

    # Si hay FFprobe: sondear códec real (no solo extensión)
    ffprobe = _find_tool("ffprobe")
    if report.exists and report.is_file and ffprobe:
        try:
            out = subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_name,sample_rate,channels,duration",
                    "-of",
                    "default=noprint_wrappers=1",
                    str(normalized),
                ],
                stderr=subprocess.DEVNULL,
                timeout=20,
                text=True,
            )
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if v:
                        report.codec_probe[k] = v
        except (OSError, subprocess.SubprocessError, TimeoutError):
            report.warnings.append("FFprobe no pudo inspeccionar el códec de audio.")

    if report.codec_probe:
        codec = report.codec_probe.get("codec_name", "").lower()
        if codec and codec not in {
            "pcm_s16le",
            "pcm_s16be",
            "aac",
            "mp3",
            "opus",
            "flac",
            "vorbis",
            "ac3",
            "eac3",
            "dts",
            "wavpack",
        }:
            report.warnings.append(
                f"Códec de audio '{codec}' no es estándar para Whisper; "
                "se recomienda transcodificación automática (se hará)."
            )
    return report


# ===========================================================================
# 5) Transcodificación automática → WAV 16kHz mono 16-bit PCM (formato nativo Whisper)
# ===========================================================================
_WHISPER_NATIVE_ARGS = [
    "-ac",
    "1",  # mono
    "-ar",
    "16000",  # 16 kHz sample rate
    "-sample_fmt",
    "s16",  # PCM 16-bit little endian
    "-vn",  # sin vídeo
    "-sn",  # sin subtítulos
    "-map",
    "0:a:0",  # primera pista de audio
    "-y",  # sobreescribe salida
]


def _random_temp_path(temp_folder: Path, suffix: str = ".wav") -> Path:
    temp_folder.mkdir(parents=True, exist_ok=True)
    return temp_folder / f"davinci_{uuid.uuid4().hex}{suffix}"


def _transcode_to_whisper_native(
    source: Path,
    temp_folder: Path,
    ffmpeg_path: str,
    timeout_s: int = 1200,
) -> tuple[Path, list[str], list[str]]:
    """Convierte ``source`` a WAV 16kHz mono s16. Devuelve (dest, warnings, cmd)."""
    warnings: list[str] = []
    dest = _random_temp_path(temp_folder, ".wav")
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-i",
        str(source),
        *_WHISPER_NATIVE_ARGS,
        str(dest),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 1024:
            tail = (proc.stderr or "").strip().splitlines()[-10:]
            raise RuntimeError("\n".join(tail) or f"exit code {proc.returncode}")
    except (OSError, subprocess.SubprocessError, TimeoutError, RuntimeError) as exc:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise RuntimeError(
            f"Transcodificación FFmpeg falló para '{source.name}'. "
            f"El códec de audio no pudo convertirse. Detalle: {exc}"
        ) from exc
    return dest, warnings, cmd


# ===========================================================================
# 6) API pública principal: todo el preflight en una sola llamada
# ===========================================================================
def ensure_readable_for_whisper(
    raw_path: str | os.PathLike[str],
    temp_folder: str | os.PathLike[str] | None = None,
    force_transcode: bool = False,
    timeout_per_file_s: int = 1200,
) -> TranscodeResult:
    """Prepara un archivo para ser leído por Whisper.

    Flujo:
      1. Sanity check (existe, es archivo, extensión OK, tamaño…)
      2. Si es un códec no estándar o ``force_transcode=True`` y hay FFmpeg,
         convierte a WAV 16kHz mono PCM s16 (formato 100% nativo Whisper).
      3. Si no hay FFmpeg, devuelve la ruta original y añade warnings
         informando al usuario.

    Devuelve :class:`TranscodeResult`.
    """
    info = media_sanity_check(raw_path)
    warnings: list[str] = list(info.warnings)

    # Si el propio sanity da errores, los subimos pero devolvemos lo que tengamos
    if info.errors:
        # Si "error" era extensión no soportada, pero existe el archivo,
        # advertimos y seguimos adelante a ver si Whisper/FFmpeg lo arreglan.
        # No interrumpimos aquí; lo convertimos en warning.
        for e in info.errors:
            warnings.append(f"[PRECHECK] {e}")
        info.errors.clear()

    # Temp folder
    project_root = Path(__file__).resolve().parent.parent
    if temp_folder is None:
        temp_folder = project_root / ".tmp"
    tf = Path(temp_folder)

    # ¿Necesitamos transcodificar?
    codec = info.codec_probe.get("codec_name", "").lower()
    needs_transcode = force_transcode or bool(
        codec
        and codec
        not in {
            "pcm_s16le",
            "pcm_s16be",
            "aac",
            "mp3",
            "opus",
            "flac",
            "vorbis",
            "ac3",
            "eac3",
            "dts",
        }
    )

    ok_ff, _ver, ffmpeg_path, _ = ffmpeg_available()
    if needs_transcode:
        if not ok_ff or not ffmpeg_path:
            warnings.append(
                "El archivo necesita transcodificación pero no se detectó FFmpeg. "
                + FFMPEG_INSTALL_HINT
            )
            return TranscodeResult(
                ready_path=info.normalized_path,
                used_transcode=False,
                temp_created=False,
                info=info,
                warnings=warnings,
            )
        # Intentar transcodificar
        try:
            dest_path, tw, cmd = _transcode_to_whisper_native(
                info.normalized_path,
                tf,
                ffmpeg_path,
                timeout_s=timeout_per_file_s,
            )
            warnings.extend(tw)
            warnings.append(
                f"Transcodificado automáticamente a WAV 16kHz mono (códec={codec or 'desconocido'})."
            )
            return TranscodeResult(
                ready_path=dest_path,
                used_transcode=True,
                temp_created=True,
                info=info,
                warnings=warnings,
                transcode_command=cmd,
            )
        except Exception as exc:
            warnings.append(f"[TRANSCODE FALLÓ] {exc}. Se intentará con el archivo original.")
            return TranscodeResult(
                ready_path=info.normalized_path,
                used_transcode=False,
                temp_created=False,
                info=info,
                warnings=warnings,
            )

    # No necesita transcode
    return TranscodeResult(
        ready_path=info.normalized_path,
        used_transcode=False,
        temp_created=False,
        info=info,
        warnings=warnings,
    )


__all__ = [
    # Extensiones
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_VIDEO_EXTENSIONS",
    "SUPPORTED_MEDIA_EXTENSIONS",
    "MEDIA_EXTENSIONS",
    "media_extensions",
    "is_media_extension",
    "is_probably_audio",
    "is_probably_video",
    # Normalización / sanity
    "normalize_media_path",
    "MediaSanityReport",
    "media_sanity_check",
    # FFmpeg
    "ffmpeg_available",
    "FFMPEG_INSTALL_HINT",
    # Principal (API pública)
    "TranscodeResult",
    "ensure_readable_for_whisper",
]
