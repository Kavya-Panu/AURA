"""
voice/language_detector.py
==========================
Thin wrapper around the STT backend's detected language, with a stable default
fallback. Kept separate so a dedicated detector can be swapped in later without
touching the recognizer.
"""
from __future__ import annotations

from core.logger import get_logger

log = get_logger("voice.language")


class LanguageDetector:
    def __init__(self, default_language: str = "en") -> None:
        self._default = default_language
        self._last: str | None = None

    def resolve(self, detected: str | None, confidence: float,
                min_confidence: float = 0.5) -> str:
        """Return a trustworthy language code, falling back to default/last."""
        if detected and confidence >= min_confidence:
            self._last = detected
            return detected
        return self._last or self._default

    @property
    def last(self) -> str | None:
        return self._last
