"""
voice/speech_recognizer.py
==========================
Turns a completed utterance (PCM bytes) into recognised text via the injected
STTBackend, applying optional noise filtering and language resolution. Produces
a RecognitionResult; publishes nothing itself (the VoiceSystem owns the bus).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.logger import get_logger
from .audio_utils import duration_s
from .backends import STTBackend
from .language_detector import LanguageDetector
from .noise_filter import NoiseFilter
from .voice_config import VoiceConfig
from .voice_exceptions import STTError

log = get_logger("voice.recognizer")


@dataclass(frozen=True)
class RecognitionResult:
    text: str
    language: str
    confidence: float
    duration_s: float
    is_empty: bool


class SpeechRecognizer:
    def __init__(self, cfg: VoiceConfig, stt: STTBackend,
                 noise: NoiseFilter | None = None,
                 language_detector: LanguageDetector | None = None) -> None:
        self._cfg = cfg
        self._stt = stt
        self._noise = noise
        self._lang = language_detector or LanguageDetector(cfg.default_language)
        self._loaded = False

    def load(self) -> None:
        self._stt.load()
        self._loaded = True

    def recognize(self, pcm: bytes) -> RecognitionResult:
        """Transcribe one utterance. Never raises on empty audio."""
        if not self._loaded:
            raise STTError("SpeechRecognizer.recognize before load()")
        dur = duration_s(pcm, self._cfg.audio.sample_rate)
        if self._noise is not None:
            pcm = self._noise.process(pcm)
        result = self._stt.transcribe(
            pcm, self._cfg.audio.sample_rate,
            None if self._cfg.stt.language is None else self._cfg.stt.language)
        text = (result.text or "").strip()
        language = self._lang.resolve(result.language, result.confidence)
        return RecognitionResult(
            text=text, language=language, confidence=result.confidence,
            duration_s=dur, is_empty=(text == ""))
