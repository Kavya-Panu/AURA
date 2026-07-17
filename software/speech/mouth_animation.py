"""
speech/mouth_animation.py
=========================
Simple viseme-based mouth animation. No perfect lip-sync - it drives the ESP32
face's mouth through four shapes (CLOSED / SMALL / MEDIUM / WIDE) roughly in
time with speech, by emitting mouth-shape commands on the Event Bus for the Face
Engine to render. It never renders directly.

Animation runs on its own thread for the estimated duration of the utterance and
stops on interruption. The shape sequence is derived cheaply from the text so
open/close cadence tracks syllable-ish rhythm without real phoneme analysis.
"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from . import speech_events as ev
from .speech_config import MouthConfig

log = get_logger("speech.mouth")


class Viseme(Enum):
    """Mouth shapes sent to the Face Engine."""
    CLOSED = "MOUTH_CLOSED"
    SMALL = "MOUTH_SMALL"
    MEDIUM = "MOUTH_MEDIUM"
    WIDE = "MOUTH_WIDE"


# Vowels tend to open the mouth wider than consonants.
_WIDE = set("aeiouAEIOU")
_MEDIUM = set("wWrRyY")


def visemes_for(text: str) -> list[Viseme]:
    """Cheap mapping from characters to a viseme sequence."""
    seq: list[Viseme] = []
    for ch in text:
        if ch.isspace():
            seq.append(Viseme.CLOSED)
        elif ch in _WIDE:
            seq.append(Viseme.WIDE)
        elif ch in _MEDIUM:
            seq.append(Viseme.MEDIUM)
        elif ch.isalpha():
            seq.append(Viseme.SMALL)
        else:
            seq.append(Viseme.CLOSED)
    return seq or [Viseme.CLOSED]


class MouthAnimator:
    """Drives mouth-shape events for the duration of an utterance. Thread-safe."""

    def __init__(self, event_bus: EventBus, config: MouthConfig,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._bus = event_bus
        self._cfg = config
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, text: str, duration_s: float) -> None:
        """Begin animating in the background for ~duration_s."""
        self.stop()  # ensure no overlap
        self._stop.clear()
        self._bus.emit(ev.MOUTH_ANIMATION_STARTED, {"duration_s": round(duration_s, 3)},
                       source="speech.mouth")
        self._thread = threading.Thread(
            target=self._run, args=(text, duration_s),
            name="speech-mouth", daemon=True)
        self._thread.start()

    def _run(self, text: str, duration_s: float) -> None:
        seq = visemes_for(text)
        interval = max(0.02, self._cfg.frame_interval_s)
        n = max(1, int(duration_s / interval))
        for i in range(n):
            if self._stop.is_set():
                break
            shape = seq[i % len(seq)]
            self._emit_shape(shape)
            self._sleep(interval)
        self._emit_shape(Viseme.CLOSED)      # always end closed
        self._bus.emit(ev.MOUTH_ANIMATION_STOPPED, {}, source="speech.mouth")

    def _emit_shape(self, shape: Viseme) -> None:
        # Mouth shapes are sent as face commands; the Face Engine renders them.
        self._bus.emit(RobotEvent.EMOTION_CHANGED,
                       {"mouth": shape.value}, source="speech.mouth")

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            self._stop.set()
            thread.join(timeout=1.0)
        with self._lock:
            self._thread = None

    @property
    def is_animating(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()
