import numpy as np

from voice.backends import WhisperSTT
from voice.voice_config import STTConfig


class NeverDecode:
    def transcribe(self, *args, **kwargs):
        raise AssertionError("Flat audio must not reach Whisper")


def test_empty_silent_and_stuck_adc_audio_cannot_hallucinate():
    stt = WhisperSTT(STTConfig())
    stt._model = NeverDecode()
    for pcm in (b"", bytes(32000), np.full(16000, 8000, dtype='<i2').tobytes()):
        result = stt.transcribe(pcm, 16000, 'en')
        assert result.text == ""
        assert result.confidence == 0.0
