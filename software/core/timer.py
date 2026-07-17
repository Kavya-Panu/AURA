"""
core/timer.py
=============
Reusable timer built for robot workloads (focus sessions, breaks, emotion
hold times, health-check intervals).

Features:
* one-shot or repeating
* pause / resume / cancel
* elapsed() and remaining() at any moment (countdown queries)
* callback on expiry (runs on the timer's own thread)
* thread-safe; uses ``time.monotonic`` so wall-clock changes can't break it

The callback is a plain callable - a behavior layer can trivially bridge it
onto the EventBus::

    Timer(120*60, lambda t: bus.emit(RobotEvent.TIMER_EXPIRED,
                                     {"name": t.name}, source="focus"),
          name="focus-session").start()
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.logger import get_logger

log = get_logger("timer")

TimerCallback = Callable[["Timer"], None]

_TICK_S = 0.005     # scheduling resolution


class Timer:
    """A pausable countdown timer running on its own daemon thread."""

    def __init__(self,
                 duration_s: float,
                 callback: TimerCallback | None = None,
                 *,
                 repeating: bool = False,
                 name: str = "timer") -> None:
        if duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        self.name = name
        self._duration = float(duration_s)
        self._callback = callback
        self._repeating = repeating

        self._lock = threading.RLock()
        self._remaining = self._duration
        self._paused = False
        self._cancelled = threading.Event()
        self._finished = threading.Event()
        self._thread: threading.Thread | None = None

    # ----------------------------------------------------------------- control
    def start(self) -> "Timer":
        """Start counting down. Returns self for chaining."""
        if self._thread is not None and self._thread.is_alive():
            return self
        self._cancelled.clear()
        self._finished.clear()
        self._thread = threading.Thread(target=self._run,
                                        name=f"timer-{self.name}", daemon=True)
        self._thread.start()
        log.debug("timer '%s' started (%.2fs, repeating=%s)",
                  self.name, self._duration, self._repeating)
        return self

    def pause(self) -> None:
        with self._lock:
            self._paused = True
        log.debug("timer '%s' paused (%.2fs remaining)",
                  self.name, self.remaining())

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        log.debug("timer '%s' resumed", self.name)

    def cancel(self) -> None:
        """Stop the timer; the callback will NOT fire."""
        self._cancelled.set()
        log.debug("timer '%s' cancelled", self.name)

    def restart(self) -> None:
        """Reset the countdown to the full duration (keeps running state)."""
        with self._lock:
            self._remaining = self._duration

    # ------------------------------------------------------------------- query
    def is_running(self) -> bool:
        return (self._thread is not None and self._thread.is_alive()
                and not self._cancelled.is_set())

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def remaining(self) -> float:
        """Seconds left in the current countdown."""
        with self._lock:
            return max(0.0, self._remaining)

    def elapsed(self) -> float:
        """Seconds consumed of the current countdown."""
        with self._lock:
            return self._duration - max(0.0, self._remaining)

    def wait(self, timeout_s: float | None = None) -> bool:
        """Block until the timer fires (one-shot) or is cancelled.
        Returns True if it finished, False on timeout."""
        return self._finished.wait(timeout=timeout_s)

    # ---------------------------------------------------------------- internal
    def _run(self) -> None:
        last = time.monotonic()
        while not self._cancelled.is_set():
            time.sleep(_TICK_S)
            now = time.monotonic()
            dt = now - last
            last = now
            with self._lock:
                if self._paused:
                    continue
                self._remaining -= dt
                expired = self._remaining <= 0.0
                if expired:
                    if self._repeating:
                        self._remaining += self._duration
                    else:
                        self._remaining = 0.0
            if expired:
                self._fire()
                if not self._repeating:
                    self._finished.set()
                    return
        self._finished.set()

    def _fire(self) -> None:
        log.debug("timer '%s' expired", self.name)
        if self._callback is None:
            return
        try:
            self._callback(self)
        except Exception:    # noqa: BLE001 - a timer must survive its callback
            log.exception("timer '%s' callback failed", self.name)
