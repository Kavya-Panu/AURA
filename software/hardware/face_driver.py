"""
hardware/face_driver.py
=======================
FaceDriver translates high-level face actions (emotion, eyes, blink, mouth,
sleep/wake, boot/shutdown) into ESP32 Face Engine serial tokens and sends them
THROUGH the HardwareManager - it never touches the serial port, and it neither
renders graphics nor generates emotions (it only expresses what it is told).

Command flow (unchanged from the architecture):
    Speech/Behavior -> FaceDriver -> HardwareManager -> SerialManager -> ESP32

A `CommandSink` Protocol is injected so the driver is testable in isolation and
so it can only reach hardware via the manager. In production the sink is the
HardwareManager's bound ``send_command``; a `MockCommandSink` records commands
for laptop/testing.
"""
from __future__ import annotations

import threading
from typing import Callable, Protocol, runtime_checkable

from core.logger import get_logger

from .device_types import CommandPriority, DeviceType

log = get_logger("hardware.face")

_FACE_DEVICE = "esp32"


@runtime_checkable
class CommandSink(Protocol):
    """Where a driver sends commands. The ONLY path to hardware is the
    HardwareManager, whose ``send_command`` matches this shape."""
    def __call__(self, device_name: str, command: str, *,
                 priority: CommandPriority = CommandPriority.NORMAL) -> None: ...


class MockCommandSink:
    """Records routed commands instead of sending them (laptop/tests)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.commands: list[tuple[str, str, CommandPriority]] = []

    def __call__(self, device_name: str, command: str, *,
                 priority: CommandPriority = CommandPriority.NORMAL) -> None:
        with self._lock:
            self.commands.append((device_name, command, priority))

    def last(self) -> tuple[str, str, CommandPriority] | None:
        with self._lock:
            return self.commands[-1] if self.commands else None

    def for_device(self, device_name: str) -> list[str]:
        with self._lock:
            return [c for d, c, _ in self.commands if d == device_name]


class FaceDriver:
    """Sends face-engine commands via the HardwareManager. Thread-safe."""

    device_type = DeviceType.ESP32

    def __init__(self, send: CommandSink, device_name: str = _FACE_DEVICE) -> None:
        self._send = send
        self._device = device_name
        self._lock = threading.RLock()

    # ------------------------------------------------------- emotion / eyes
    def set_emotion(self, emotion_token: str) -> None:
        """Send an emotion token (e.g. "HAPPY", "THINK"). The token is produced
        elsewhere (Speech/Behavior); the driver only forwards it."""
        self._route(str(emotion_token), CommandPriority.HIGH)

    def look(self, x: float, y: float) -> None:
        """Move the eyes to a normalized gaze target (x,y in -1..+1)."""
        x = _clamp(x, -1.0, 1.0)
        y = _clamp(y, -1.0, 1.0)
        self._route(f"EYES:{x:.2f},{y:.2f}", CommandPriority.NORMAL)

    def center_eyes(self) -> None:
        self.look(0.0, 0.0)

    def blink(self, times: int = 1) -> None:
        self._route(f"BLINK:{max(1, int(times))}", CommandPriority.NORMAL)

    # --------------------------------------------------------------- mouth
    def set_mouth(self, shape: str) -> None:
        """Set a mouth viseme shape (e.g. "MOUTH_WIDE"). Approximate lip-sync is
        driven by the Speech layer; the driver only forwards each shape."""
        self._route(f"MOUTH:{shape}", CommandPriority.NORMAL)

    def close_mouth(self) -> None:
        self.set_mouth("MOUTH_CLOSED")

    # ------------------------------------------------------- power / boot
    def sleep(self) -> None:
        self._route("SLEEP", CommandPriority.HIGH)

    def wake(self) -> None:
        self._route("WAKE", CommandPriority.HIGH)

    def boot(self) -> None:
        self._route("BOOT", CommandPriority.CRITICAL)

    def shutdown(self) -> None:
        self._route("SHUTDOWN", CommandPriority.CRITICAL)

    # ------------------------------------------------------------- internal
    def _route(self, command: str, priority: CommandPriority) -> None:
        with self._lock:
            self._send(self._device, command, priority=priority)
        log.debug("face -> %s (%s)", command, priority.name)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
