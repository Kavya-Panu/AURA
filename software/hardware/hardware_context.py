"""
hardware/hardware_context.py
============================
HardwareContext holds the HAL's runtime state: connected devices, battery level,
current face emotion, servo positions, LED state, propeller state, the last
command, health status, connection state, and runtime statistics. Runtime only -
it persists nothing. Thread-safe; other modules read an immutable snapshot.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .device_types import ConnectionState, HealthState


@dataclass(frozen=True)
class HardwareSnapshot:
    connected_devices: tuple[str, ...]
    connection_state: str
    battery_percent: float | None
    battery_charging: bool | None
    face_emotion: str | None
    servo_positions: dict[str, float]
    led_state: dict[str, Any] | None
    propeller_running: bool
    propeller_speed: int
    last_command: tuple[str, str] | None
    health: str
    stats: dict[str, int]
    updated_at: float


class HardwareContext:
    """Mutable, lock-guarded runtime state for the HAL. No persistence."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()

        self._connected: set[str] = set()
        self._connection_state = ConnectionState.DISCONNECTED
        self._battery_percent: float | None = None
        self._battery_charging: bool | None = None
        self._face_emotion: str | None = None
        self._servo_positions: dict[str, float] = {}
        self._led_state: dict[str, Any] | None = None
        self._propeller_running = False
        self._propeller_speed = 0
        self._last_command: tuple[str, str] | None = None
        self._health = HealthState.UNKNOWN
        self._stats: dict[str, int] = {"commands": 0, "errors": 0,
                                       "reconnects": 0}

    # --------------------------------------------------------- mutators
    def set_connected(self, name: str, connected: bool) -> None:
        with self._lock:
            if connected:
                self._connected.add(name)
            else:
                self._connected.discard(name)

    def set_connection_state(self, state: ConnectionState) -> None:
        with self._lock:
            self._connection_state = state

    def set_battery(self, percent: float | None, charging: bool | None) -> None:
        with self._lock:
            if percent is not None:
                self._battery_percent = percent
            if charging is not None:
                self._battery_charging = charging

    def set_face_emotion(self, emotion: str) -> None:
        with self._lock:
            self._face_emotion = emotion

    def set_servo(self, channel: str, angle: float) -> None:
        with self._lock:
            self._servo_positions[channel] = angle

    def set_led(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._led_state = dict(state)

    def set_propeller(self, running: bool, speed: int) -> None:
        with self._lock:
            self._propeller_running = running
            self._propeller_speed = speed

    def set_health(self, health: HealthState) -> None:
        with self._lock:
            self._health = health

    def record_command(self, device: str, command: str) -> None:
        with self._lock:
            self._last_command = (device, command)
            self._stats["commands"] += 1

    def record_error(self) -> None:
        with self._lock:
            self._stats["errors"] += 1

    def record_reconnect(self) -> None:
        with self._lock:
            self._stats["reconnects"] += 1

    # --------------------------------------------------------- accessors
    @property
    def connected_devices(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._connected))

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def snapshot(self) -> HardwareSnapshot:
        with self._lock:
            return HardwareSnapshot(
                connected_devices=tuple(sorted(self._connected)),
                connection_state=self._connection_state.name,
                battery_percent=self._battery_percent,
                battery_charging=self._battery_charging,
                face_emotion=self._face_emotion,
                servo_positions=dict(self._servo_positions),
                led_state=None if self._led_state is None else dict(self._led_state),
                propeller_running=self._propeller_running,
                propeller_speed=self._propeller_speed,
                last_command=self._last_command,
                health=self._health.name,
                stats=dict(self._stats),
                updated_at=self._clock())
