"""Smoke test de transcripcion Whisper.

Se salta automaticamente si faltan dependencias (torch/transformers) o el
audio de prueba — no esta pensado para CI, donde esas deps no se instalan.
"""

import pytest

transformers = pytest.importorskip("transformers", reason="transformers no instalado")

AUDIO = "path/to/your/audio/file.ogg"


def test_transcription(tmp_path):
    import os

    if not os.path.exists(AUDIO):
        pytest.skip(f"Audio de prueba no encontrado: {AUDIO}")
    recognizer = transformers.pipeline(
        "automatic-speech-recognition", model="facebook/whisper-large-v3-turbo"
    )
    result = recognizer(AUDIO)
    assert "text" in result or "transcription" in result
