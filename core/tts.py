"""Generación de voz en off (TTS) y doblaje de vídeo.

Pipeline opcional post-transcripción:
  1. ``generate_voiceover``  -> voz_en_off.mp3  (edge-tts, fallback SAPI Windows)
  2. ``segments_to_srt``     -> subtitulos.srt  (a partir de los segmentos Whisper)
  3. ``mux_voiceover``       -> video_doblado.mp4 (voz nueva + subtítulos quemados)

edge-tts usa voces neuronales de Microsoft (gratis, requiere internet).
Si falla, se intenta con SAPI de Windows (voces locales tipo Helena).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

DEFAULT_VOICE = "es-ES-ElviraNeural"


def generate_voiceover(
    text: str,
    out_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
) -> Path:
    """Genera un MP3 leyendo ``text`` en voz alta.

    Intenta edge-tts primero; si no hay red o la lib no está, cae a SAPI
    (Windows) que produce un WAV. Devuelve la ruta real del archivo creado.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = (text or "").strip()
    if not text:
        raise ValueError("No hay texto que narrar.")

    try:
        _edge_tts(text, out_path, voice, rate)
        return out_path
    except Exception:
        # Fallback: SAPI (solo Windows). Genera WAV en vez de MP3.
        if sys.platform != "win32":
            raise
        wav_path = out_path.with_suffix(".wav")
        _sapi_tts(text, wav_path, rate)
        return wav_path


async def _edge_tts_async(text: str, out_path: Path, voice: str, rate: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(out_path))


def _edge_tts(text: str, out_path: Path, voice: str, rate: str) -> None:
    _force_threaded_resolver()
    asyncio.run(_edge_tts_async(text, out_path, voice, rate))
    if not out_path.exists() or out_path.stat().st_size < 1000:
        raise RuntimeError("edge-tts no generó audio válido")


def _force_threaded_resolver() -> None:
    """Si ``aiodns`` está instalado, aiohttp lo usa como resolvedor y puede
    fallar en redes donde el DNS UDP de c-ares no funciona (VPN, firewall…).
    Forzamos el resolvedor del sistema operativo."""
    try:
        import aiohttp.connector
        from aiohttp.resolver import ThreadedResolver

        aiohttp.connector.DefaultResolver = ThreadedResolver
    except Exception:
        pass


def _sapi_tts(text: str, wav_path: Path, rate: str) -> None:
    """Fallback con System.Speech de Windows (voces locales, p.ej. Helena)."""
    # rate "+10%" / "-10%" -> escala SAPI -10..10
    try:
        pct = int(rate.replace("%", "").replace("+", ""))
    except ValueError:
        pct = 0
    sapi_rate = max(-10, min(10, pct // 10))

    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {sapi_rate}; "
        "$v = $s.GetInstalledVoices() | Where-Object {$_.VoiceInfo.Culture.Name -like 'es*'} "
        "| Select-Object -First 1; "
        "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
        f"$s.SetOutputToWaveFile('{wav_path}'); "
        "$s.Speak([Console]::In.ReadToEnd()); "
        "$s.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        input=text.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    if not wav_path.exists() or wav_path.stat().st_size < 1000:
        raise RuntimeError("SAPI no generó audio válido")


def segments_to_srt(segments: list[dict], out_path: Path) -> Path:
    """Convierte los segmentos de Whisper a un fichero .srt de subtítulos."""
    out_path = Path(out_path)
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(seg['start'])} --> {_srt_ts(seg['end'])}")
        lines.append(str(seg["text"]).strip())
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _srt_ts(seconds: float) -> str:
    ms = round(float(seconds) * 1000)
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def mux_voiceover(
    video_path: Path,
    audio_path: Path,
    out_path: Path,
    srt_path: Path | None = None,
) -> Path:
    """Crea ``video_doblado.mp4``: vídeo original + voz en off (+ subtítulos).

    Requiere ffmpeg en PATH. Si ``srt_path`` se indica, los subtítulos se
    queman sobre la imagen (estilo TikTok/Shorts).
    """
    video_path = Path(video_path).resolve()
    audio_path = Path(audio_path).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # El filtro subtitles de ffmpeg es quisquilloso con rutas Windows (los ':'
    # se interpretan como separadores). Ejecutamos con cwd=carpeta del job y
    # referenciamos el .srt por nombre simple.
    work = out_path.parent
    vf_args: list[str] = []
    if srt_path:
        srt_path = Path(srt_path).resolve()
        srt_ref = srt_path.name if srt_path.parent == work else str(srt_path).replace("\\", "/")
        vf_args = ["-vf", f"subtitles='{srt_ref}'"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        *vf_args,
        "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest",
        out_path.name,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg mux falló: {proc.stderr[-400:]}")
    return out_path
