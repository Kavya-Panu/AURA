"""
vision/fatigue_detector.py
==========================
Fatigue estimation (final Vision stage). A pure Event-Bus transformer - it
consumes signals already published by the eye-contact and head-pose detectors
(and optional yawn events) and estimates simple study-related fatigue, publishing
``USER_TIRED``.

Because it only reacts to bus events, it is completely independent of MediaPipe/
YOLO and never touches a camera, model, or hardware. It subscribes to:
* ``LOOKING_AWAY``     - repeated/long look-aways contribute to fatigue,
* ``HEAD_DOWN``        - a lowered head contributes,
* ``LOOKING_AT_ROBOT`` - resets the look-away streak.

**This is NOT a medical diagnosis** - it is only a lightweight behavioural
estimate, and it emits ``USER_TIRED`` at most once per cooldown window.

Implements the Stage-1 Detector protocol (so the VisionManager can own it), but
does no inference itself.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from core.constants import RobotEvent
from core.event_bus import Event, EventBus
from core.logger import get_logger

log = get_logger("vision.fatigue")


@dataclass
class FatigueConfig:
    """Thresholds for the fatigue estimate (all configurable, no magic numbers)."""
    look_away_events_for_tired: int = 4     # repeated look-aways in the window
    long_look_away_s: float = 6.0           # a single long look-away
    head_down_events_for_tired: int = 3     # repeated head-down in the window
    window_s: float = 60.0                  # sliding window for counting
    cooldown_s: float = 30.0                # min gap between USER_TIRED emits


class FatigueDetector:
    """Estimates fatigue from vision events and publishes USER_TIRED.

    Satisfies the Stage-1 Detector protocol; it is an event transformer, not an
    inference detector, so it needs no frame buffer or model.
    """

    name = "fatigue"

    def __init__(self, event_bus: EventBus,
                 config: FatigueConfig | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._cfg = config or FatigueConfig()
        self._clock = clock

        self._lock = threading.RLock()
        self._look_away_times: list[float] = []
        self._head_down_times: list[float] = []
        self._last_tired = -1e9
        self._subs: list[int] = []

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        pass

    def start(self) -> None:
        if self._subs:
            return
        self._subs = [
            self._bus.subscribe(RobotEvent.LOOKING_AWAY, self._on_look_away,
                                priority=30),
            self._bus.subscribe(RobotEvent.LOOKING_AT_ROBOT, self._on_look_back,
                                priority=30),
            self._bus.subscribe(RobotEvent.HEAD_DOWN, self._on_head_down,
                                priority=30),
        ]
        log.info("fatigue detector started")

    def stop(self) -> None:
        for sub in self._subs:
            self._bus.unsubscribe(sub)
        self._subs = []
        with self._lock:
            self._look_away_times.clear()
            self._head_down_times.clear()

    def health_check(self) -> bool:
        return bool(self._subs)

    # ------------------------------------------------------------- handlers
    def _on_look_away(self, event: Event) -> None:
        now = self._clock()
        duration = float(event.data.get("duration_s", 0.0))
        with self._lock:
            self._look_away_times.append(now)
            self._prune(now)
            long_away = duration >= self._cfg.long_look_away_s
            repeated = len(self._look_away_times) >= self._cfg.look_away_events_for_tired
        if long_away or repeated:
            self._maybe_emit(now, "look_away")

    def _on_look_back(self, event: Event) -> None:
        with self._lock:
            self._look_away_times.clear()   # engaged again -> reset the streak

    def _on_head_down(self, event: Event) -> None:
        now = self._clock()
        with self._lock:
            self._head_down_times.append(now)
            self._prune(now)
            repeated = len(self._head_down_times) >= self._cfg.head_down_events_for_tired
        if repeated:
            self._maybe_emit(now, "head_down")

    # -------------------------------------------------------------- helpers
    def _prune(self, now: float) -> None:
        cutoff = now - self._cfg.window_s
        self._look_away_times = [t for t in self._look_away_times if t >= cutoff]
        self._head_down_times = [t for t in self._head_down_times if t >= cutoff]

    def _maybe_emit(self, now: float, reason: str) -> None:
        with self._lock:
            if now - self._last_tired < self._cfg.cooldown_s:
                return
            self._last_tired = now
        self._bus.emit(RobotEvent.USER_TIRED,
                       {"reason": reason, "note": "behavioural estimate, "
                        "not a medical diagnosis"},
                       source=self.name)
        log.info("USER_TIRED (%s)", reason)
