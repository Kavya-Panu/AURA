"""
speech/expression_manager.py
============================
Coordinates the face EXPRESSION while speaking. It holds a single, stable
expression for the whole utterance (no per-word switching), emits it via the
existing EMOTION_CHANGED event (so a FaceLink turns it into an ESP32 token), and
schedules natural blinks. It sends commands only - it never renders.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from . import speech_events as ev
from .speech_config import ExpressionConfig

log = get_logger("speech.expression")


class ExpressionManager:
    """Sets and holds a facial expression during speech; schedules blinks."""

    def __init__(self, event_bus: EventBus, config: ExpressionConfig,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._cfg = config
        self._clock = clock
        self._lock = threading.RLock()
        self._current: str | None = None

    def set_expression(self, emotion_token: str) -> None:
        """Set the held expression for the current utterance. Idempotent - the
        same expression is not re-emitted, so it stays stable while speaking."""
        with self._lock:
            if self._cfg.hold_expression and self._current == emotion_token:
                return
            self._current = emotion_token
        self._bus.emit(ev.EXPRESSION_CHANGED, {"emotion": emotion_token},
                       source="speech.expression")
        # Send the actual face command (same convention as the Behavior layer).
        self._bus.emit(RobotEvent.EMOTION_CHANGED, {"emotion": emotion_token},
                       source="speech.expression")

    def reset(self, to_token: str = "NORMAL") -> None:
        """Return to a neutral expression after speaking."""
        with self._lock:
            self._current = to_token
        self._bus.emit(ev.EXPRESSION_CHANGED, {"emotion": to_token},
                       source="speech.expression")
        self._bus.emit(RobotEvent.EMOTION_CHANGED, {"emotion": to_token},
                       source="speech.expression")

    @property
    def current(self) -> str | None:
        with self._lock:
            return self._current
