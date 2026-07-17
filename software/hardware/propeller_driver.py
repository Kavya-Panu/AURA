"""
hardware/propeller_driver.py
============================
PropellerDriver controls the propeller motor by sending commands THROUGH the
HardwareManager. Supports start/stop, speed control, timed runs, and a mandatory
SAFETY TIMEOUT that stops the motor if it is left running too long. Timed runs
and the safety watchdog run on background threads; the driver never touches
serial itself.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.logger import get_logger

from .device_types import CommandPriority, DeviceType
from .face_driver import CommandSink

log = get_logger("hardware.propeller")


class PropellerDriver:
    """Drives the propeller via the HardwareManager. Thread-safe, with a safety
    timeout that always stops a runaway motor."""

    device_type = DeviceType.PROPELLER

    def __init__(self, send: CommandSink, device_name: str = "esp32",
                 channel: str = "prop", safety_timeout_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._send = send
        self._device = device_name
        self._channel = channel
        self._safety_timeout_s = safety_timeout_s
        self._clock = clock
        self._sleep = sleep

        self._lock = threading.RLock()
        self._speed = 0
        self._running = False
        self._watchdog: threading.Thread | None = None
        self._timed: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def speed(self) -> int:
        with self._lock:
            return self._speed

    # ------------------------------------------------------------- control
    def start(self, speed: int = 100) -> None:
        """Start the propeller at 0..100% and arm the safety timeout."""
        speed = max(1, min(100, int(speed)))
        with self._lock:
            self._speed = speed
            self._running = True
        self._route(f"PROP:{self._channel}:{speed}", CommandPriority.HIGH)
        self._arm_watchdog()

    def set_speed(self, speed: int) -> None:
        if not self.running:
            return
        speed = max(0, min(100, int(speed)))
        with self._lock:
            self._speed = speed
        if speed == 0:
            self.stop()
        else:
            self._route(f"PROP:{self._channel}:{speed}", CommandPriority.NORMAL)

    def stop(self) -> None:
        """Stop the propeller immediately and cancel timers."""
        self._cancel.set()
        with self._lock:
            self._speed = 0
            self._running = False
        self._route(f"PROP:{self._channel}:0", CommandPriority.HIGH)

    def run_for(self, duration_s: float, speed: int = 100) -> None:
        """Run for a fixed duration then stop, on a background thread."""
        self.start(speed)
        def run() -> None:
            end = self._clock() + duration_s
            while self._clock() < end:
                if self._cancel.is_set():
                    return
                self._sleep(0.01)
            self.stop()
        self._timed = threading.Thread(target=run, name="prop-timed", daemon=True)
        self._timed.start()

    # -------------------------------------------------------- safety
    def _arm_watchdog(self) -> None:
        self._cancel.clear()
        def guard() -> None:
            end = self._clock() + self._safety_timeout_s
            while self._clock() < end:
                if self._cancel.is_set():
                    return
                self._sleep(0.01)
            if self.running:
                log.warning("propeller safety timeout -> stopping")
                self.stop()
        self._watchdog = threading.Thread(target=guard, name="prop-watchdog",
                                          daemon=True)
        self._watchdog.start()

    # ------------------------------------------------------------- internal
    def _route(self, command: str, priority: CommandPriority) -> None:
        self._send(self._device, command, priority=priority)
        log.debug("propeller -> %s (%s)", command, priority.name)
