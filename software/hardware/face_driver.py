"""
hardware/face_driver.py
=======================
FaceDriver translates high-level face actions into the exact serial protocol
implemented by AURA's current ESP32 firmware.

Command flow:
    Speech/Behavior/Brain bridge -> FaceDriver -> HardwareManager
    -> SerialManager -> ESP32

The driver never imports pyserial and never opens a port.
"""
from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from core.logger import get_logger

from .device_types import CommandPriority, DeviceType
from .esp32_protocol import (
    blink_command,
    brightness_command,
    emotion_command,
    focus_command,
    gaze_command,
)

log = get_logger("hardware.face")

_FACE_DEVICE = "esp32"


@runtime_checkable
class CommandSink(Protocol):
    """Where a driver sends commands. HardwareManager supplies this callable."""
    def __call__(self, device_name: str, command: str, *,
                 priority: CommandPriority = CommandPriority.NORMAL) -> None: ...


class MockCommandSink:
    """Records routed commands instead of sending them."""

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
            return [command for device, command, _ in self.commands
                    if device == device_name]


class FaceDriver:
    """High-level face API backed by the current ESP32 line protocol."""

    device_type = DeviceType.ESP32

    def __init__(self, send: CommandSink, device_name: str = _FACE_DEVICE) -> None:
        self._send = send
        self._device = device_name
        self._lock = threading.RLock()

    # ------------------------------------------------------- emotion / eyes
    def set_emotion(self, emotion_token: str) -> None:
        self._route(emotion_command(emotion_token), CommandPriority.HIGH)

    def look(self, x: float, y: float) -> None:
        self._route(gaze_command(x, y), CommandPriority.NORMAL)

    def look_left(self) -> None:
        self._route("LOOK LEFT", CommandPriority.NORMAL)

    def look_right(self) -> None:
        self._route("LOOK RIGHT", CommandPriority.NORMAL)

    def look_up(self) -> None:
        self._route("LOOK UP", CommandPriority.NORMAL)

    def look_down(self) -> None:
        self._route("LOOK DOWN", CommandPriority.NORMAL)

    def center_eyes(self) -> None:
        self._route("LOOK CENTER", CommandPriority.NORMAL)

    def blink(self, times: int = 1) -> None:
        self._route(blink_command(times), CommandPriority.NORMAL)

    # --------------------------------------------------------------- focus
    def start_focus(self) -> None:
        self._route(focus_command(True), CommandPriority.HIGH)

    def stop_focus(self) -> None:
        self._route(focus_command(False), CommandPriority.HIGH)

    # --------------------------------------------------------------- display
    def set_brightness(self, level: int) -> None:
        self._route(brightness_command(level), CommandPriority.NORMAL)

    def status(self) -> None:
        self._route("STATUS", CommandPriority.LOW)

    def ping(self) -> None:
        self._route("PING", CommandPriority.LOW)

    # --------------------------------------------------------------- mouth
    def set_mouth(self, shape: str) -> None:
        """Reserved for a future firmware TALK/viseme protocol.

        The current ESP32 parser does not accept MOUTH:* commands. Silently
        ignoring them prevents ERR_UNKNOWN_COMMAND traffic while preserving the
        Speech layer API.
        """
        log.debug("mouth command ignored until firmware visemes are implemented: %s",
                  shape)

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
