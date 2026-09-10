"""
voice/speech_recognizer.py
==========================
Turns a completed utterance (PCM bytes) into recognised text via the injected
STTBackend, applying optional noise filtering and language resolution. Produces
a RecognitionResult; publishes nothing itself (the VoiceSystem owns the bus).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.logger import get_logger
from .audio_utils import duration_s
from .backends import STTBackend
from .language_detector import LanguageDetector
from .noise_filter import NoiseFilter
from .voice_config import VoiceConfig
from .voice_exceptions import STTError

log = get_logger("voice.recognizer")


_DOMAIN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\be\s*s\s*p\s*(?:thirty[ -]?two|3[ -]?2)\s*s\s*(?:three|3)\b", "ESP32-S3"),
    (r"\be\s*s\s*p\s*(?:thirty[ -]?two|3[ -]?2)\b", "ESP32"),
    (r"\bjetson\s+nano\b", "Jetson Nano"),
    (r"\barduino\b", "Arduino"),
    (r"\bopen\s*c\s*v\b", "OpenCV"),
    (r"\bmedia\s*pipe\b", "MediaPipe"),
    (r"\bplatform\s*i\s*o\b", "PlatformIO"),
    (r"\bollama\b", "Ollama"),
    (r"\bq[ -]?wen\b", "Qwen"),
    (r"\bili\s*9\s*3\s*4\s*1\b", "ILI9341"),
    (r"\bes\s*8\s*3\s*1\s*1\b", "ES8311"),
    (r"\b(?:hey\s+)?(?:aura|ora)\b", "AURA"),
)


def normalize_transcript(text: str) -> str:
    """Clean common speech-decoder errors without rewriting normal sentences."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    for pattern, replacement in _DOMAIN_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    # Whisper sometimes emits a complete short sentence twice. Remove only
    # immediately repeated sentences, preserving intentional repeated words.
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    deduplicated: list[str] = []
    for sentence in sentences:
        key = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        previous = (
            re.sub(r"[^a-z0-9]+", " ", deduplicated[-1].lower()).strip()
            if deduplicated else ""
        )
        if key and key == previous:
            continue
        deduplicated.append(sentence)
    cleaned = " ".join(deduplicated).strip()

    # Also handle an exact duplicated phrase when Whisper supplied no terminal
    # punctuation between the two copies.
    words = cleaned.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        left = re.sub(r"\W+", "", " ".join(words[:half]).lower())
        right = re.sub(r"\W+", "", " ".join(words[half:]).lower())
        if left and left == right:
            cleaned = " ".join(words[:half])
    return cleaned


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
        text = normalize_transcript(result.text)
        language = self._lang.resolve(result.language, result.confidence)
        return RecognitionResult(
            text=text, language=language, confidence=result.confidence,
            duration_s=dur, is_empty=(text == ""))
