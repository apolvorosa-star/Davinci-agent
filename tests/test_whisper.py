#!/usr/bin/env python

import pytest
from transformers import pipeline

def test_transcription():
    recognizer = pipeline('automatic-speech-recognition', model='facebook/whisper-large-v3-turbo')
    result = recognizer('path/to/your/audio/file.ogg')
    assert 'transcription' in result
