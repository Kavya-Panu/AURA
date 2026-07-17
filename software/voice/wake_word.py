"""
voice/wake_word.py
==================
Wake-word detection. The real deployment can swap in openWakeWord/Porcupine via
the WakeWordBackend Protocol; the built-in detector is a lightweight
text/energy detector used when a streaming keyword model isn't present, plus a
FakeWakeWord for tests.

The detector operates on short rolling transcripts OR on an injected backend's
score. It enforces a cooldown so one utterance can't fire repeatedly.
"""
from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from core.logger import get_logger
from .voice_config import WakeWordConfig

log = get_logger("voice.wake")


@runtime_checkable
class WakeWordBackend(Protocol):
    """Streaming detector: feed a frame, get a 0..1 score."""
    def score_frame(self, frame: bytes) -> float: ...
    def reset(self) -> None: ...


class FakeWakeWord:
    """Emits a scripted score sequence; for tests."""
    def __init__(self, scores: list[float] | None = None) -> None:
        self._scores = list(scores or [])
        self._i = 0

    def score_frame(self, frame: bytes) -> float:
        if self._i < len(self._scores):
            s = self._scores[self._i]; self._i += 1
            return s
        return 0.0

    def reset(self) -> None:
        self._i = 0


class WakeWordDetector:
    """Wraps a backend (optional) and applies threshold + cooldown. Also offers
    text-based detection for the fallback path (matching against phrases in a
    short transcript)."""

    def __init__(self, cfg: WakeWordConfig,
                 backend: WakeWordBackend | None = None,
                 clock=time.monotonic) -> None:
        self._cfg = cfg
        self._backend = backend
        self._clock = clock
        self._last_fire = -1e9
        self._phrases = tuple(p.lower() for p in cfg.phrases)

    def _cooled_down(self) -> bool:
        return (self._clock() - self._last_fire) >= self._cfg.cooldown_s

    def process_frame(self, frame: bytes) -> bool:
        """Streaming detection via the backend. True if the wake word fires."""
        if self._backend is None:
            return False
        score = self._backend.score_frame(frame)
        if score >= self._cfg.confidence_threshold and self._cooled_down():
            self._last_fire = self._clock()
            log.debug("wake word (score %.2f)", score)
            return True
        return False

    def check_text(self, text: str) -> tuple[bool, str]:
        """Fallback detection: does a short transcript start with / contain a
        wake phrase? Returns (fired, remaining_text_after_phrase)."""
        low = text.lower().strip()
        for phrase in sorted(self._phrases, key=len, reverse=True):
            if low.startswith(phrase) or f" {phrase} " in f" {low} ":
                if self._cooled_down():
                    self._last_fire = self._clock()
                    idx = low.find(phrase) + len(phrase)
                    return True, text[idx:].lstrip(" ,.!?;:-")
        return False, text
