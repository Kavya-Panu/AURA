"""
hardware/servo_driver.py
========================
ServoDriver moves servos (head pan/tilt, eye servos, neck tracking) by sending
angle commands THROUGH the HardwareManager. It supports move-to-angle, smooth
(stepped) movement, speed control, movement limits, and calibration offsets.

No inverse kinematics - each servo is driven directly by angle. Smooth movement
runs on a background thread so callers never block; movement is thread-safe and
cancellable. The driver never touches serial itself.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from core.logger import get_logger

from .device_types import CommandPriority, DeviceType
from .face_driver import CommandSink

log = get_logger("hardware.servo")


@dataclass
class ServoLimits:
    """Per-servo configuration: allowed angle range, calibration offset, and
    default smooth-move speed (degrees/second)."""
    min_angle: float = 0.0
    max_angle: float = 180.0
    calibration_offset: float = 0.0
    default_speed_dps: float = 120.0
    step_deg: float = 2.0            # granularity of smooth movement


class ServoDriver:
    """Drives one named servo channel via the HardwareManager. Thread-safe."""

    device_type = DeviceType.SERVO

    def __init__(self, send: CommandSink, channel: str,
                 limits: ServoLimits | None = None,
                 device_name: str = "esp32",
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._send = send
        self._channel = channel
        self._limits = limits or ServoLimits()
        self._device = device_name
        self._clock = clock
        self._sleep = sleep

        self._lock = threading.RLock()
        self._angle = self._clamp((self._limits.min_angle +
                                   self._limits.max_angle) / 2.0)
        self._move_thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def channel(self) -> str:
        return self._channel

    @property
    def angle(self) -> float:
        with self._lock:
            return self._angle

    # ------------------------------------------------------- movement
    def move_to(self, angle: float, *,
                priority: CommandPriority = CommandPriority.NORMAL) -> float:
        """Immediately move to an angle (clamped to limits, calibration applied).
        Returns the clamped target angle."""
        target = self._clamp(angle)
        self._emit(target, priority)
        with self._lock:
            self._angle = target
        return target

    def move_smooth(self, angle: float, *, speed_dps: float | None = None,
                    blocking: bool = False) -> None:
        """Move gradually to an angle at `speed_dps` deg/s (default from limits).
        Runs on a background thread unless `blocking`. Cancels any in-flight
        smooth move first."""
        self.cancel()
        target = self._clamp(angle)
        speed = speed_dps if speed_dps and speed_dps > 0 else self._limits.default_speed_dps

        def run() -> None:
            self._cancel.clear()
            step = max(0.1, self._limits.step_deg)
            interval = step / speed
            while not self._cancel.is_set():
                with self._lock:
                    current = self._angle
                delta = target - current
                if abs(delta) <= step:
                    self.move_to(target)
                    break
                nxt = current + (step if delta > 0 else -step)
                self.move_to(nxt)
                self._sleep(interval)

        if blocking:
            run()
        else:
            self._move_thread = threading.Thread(
                target=run, name=f"servo-{self._channel}", daemon=True)
            self._move_thread.start()

    def cancel(self) -> None:
        """Cancel an in-flight smooth movement."""
        self._cancel.set()
        thread = self._move_thread
        if thread is not None and thread.is_alive() and \
                thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._move_thread = None

    # ---------------------------------------------------- calibration
    def calibrate(self, offset: float) -> None:
        with self._lock:
            self._limits.calibration_offset = offset

    def center(self) -> None:
        self.move_to((self._limits.min_angle + self._limits.max_angle) / 2.0)

    # ------------------------------------------------------------- internal
    def _clamp(self, angle: float) -> float:
        return max(self._limits.min_angle, min(self._limits.max_angle, angle))

    def _emit(self, angle: float, priority: CommandPriority) -> None:
        physical = angle + self._limits.calibration_offset
        self._send(self._device, f"SERVO:{self._channel}:{physical:.1f}",
                   priority=priority)
        log.debug("servo %s -> %.1f (physical %.1f)", self._channel, angle, physical)
