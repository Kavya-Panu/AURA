"""
speech/speech_context.py
========================
Thread-safe snapshot of the Speech Manager's live state.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto


class SpeechState(Enum):
    IDLE = auto()
    THINKING = auto()
    SPEAKING = auto()
    CANCELLING = auto()


@dataclass(frozen=True)
class SpeechSnapshot:
    state: str
    emotion: str
    profile: str
    provider: str
    speaking_duration_s: float
    queue_length: int
    updated_at: float


class SpeechContext:
    """Mutable, lock-guarded Speech state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = SpeechState.IDLE
        self._emotion = "NORMAL"
        self._profile = ""
        self._provider = ""
        self._speak_start = 0.0
        self._speaking_duration = 0.0
        self._queue_length = 0

    def set_state(self, state: SpeechState) -> None:
        with self._lock:
            self._state = state

    def set_style(self, emotion: str, profile: str) -> None:
        with self._lock:
            self._emotion = emotion
            self._profile = profile

    def set_provider(self, provider: str) -> None:
        with self._lock:
            self._provider = provider

    def mark_speaking(self, duration_s: float) -> None:
        with self._lock:
            self._speak_start = time.monotonic()
            self._speaking_duration = duration_s

    def set_queue_length(self, n: int) -> None:
        with self._lock:
            self._queue_length = n

    @property
    def state(self) -> SpeechState:
        with self._lock:
            return self._state

    def snapshot(self) -> SpeechSnapshot:
        with self._lock:
            return SpeechSnapshot(
                state=self._state.name, emotion=self._emotion,
                profile=self._profile, provider=self._provider,
                speaking_duration_s=self._speaking_duration,
                queue_length=self._queue_length, updated_at=time.monotonic())
