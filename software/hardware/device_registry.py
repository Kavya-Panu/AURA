"""
hardware/device_registry.py
===========================
Devices and the registry that manages them.

Every device implements the Device Protocol (connect/disconnect/health_check/
send_command). Concrete devices are injected, so the HardwareManager depends only
on the interface and NEW device kinds are added without changing it (Open/Closed).

Two general-purpose devices ship:
    * SerialDevice - a device whose commands go out over the ESP32 serial link
      (the ESP32 face, and by extension the display/servo/LED/propeller it drives
      via serial tokens). Constructed with a `send` callable injected by the
      HardwareManager (which owns the SerialManager) - so the device never
      touches the port directly.
    * MockDevice   - a fully in-process device (battery, camera, microphone, or
      any peripheral) with settable health/telemetry, so the whole robot runs on
      a laptop.
"""
from __future__ import annotations

import threading
from typing import Callable, Protocol, runtime_checkable

from core.logger import get_logger

from .device_types import (
    CommandPriority, ConnectionState, DeviceType, HealthState)
from .hardware_exceptions import DeviceError, DeviceNotFound

log = get_logger("hardware.device")


@runtime_checkable
class Device(Protocol):
    """Common interface every hardware device implements."""
    name: str
    device_type: DeviceType
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def health_check(self) -> HealthState: ...
    def send_command(self, command: str,
                     priority: CommandPriority = CommandPriority.NORMAL) -> None: ...


class SerialDevice:
    """A device driven over the ESP32 serial link. The `send` callable is
    injected by the HardwareManager (backed by the SerialManager), so this
    device never opens a port itself."""

    def __init__(self, name: str, device_type: DeviceType,
                 send: Callable[[str, CommandPriority], bool],
                 is_link_up: Callable[[], bool]) -> None:
        self.name = name
        self.device_type = device_type
        self._send = send
        self._is_link_up = is_link_up
        self._connected = False
        self._lock = threading.RLock()

    def connect(self) -> None:
        with self._lock:
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._is_link_up()

    def health_check(self) -> HealthState:
        return HealthState.HEALTHY if self.is_connected() else HealthState.FAULT

    def send_command(self, command: str,
                     priority: CommandPriority = CommandPriority.NORMAL) -> None:
        if not self._is_link_up():
            raise DeviceError(f"{self.name}: serial link down")
        if not self._send(command, priority):
            raise DeviceError(f"{self.name}: command queue full")


class MockDevice:
    """Fully in-process device for laptop operation. Records commands and exposes
    settable health + telemetry (e.g. battery percent)."""

    def __init__(self, name: str, device_type: DeviceType,
                 telemetry: dict | None = None) -> None:
        self.name = name
        self.device_type = device_type
        self._connected = False
        self._health = HealthState.HEALTHY
        self._lock = threading.RLock()
        self.commands: list[str] = []
        self.telemetry: dict = dict(telemetry or {})

    def connect(self) -> None:
        with self._lock:
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def set_health(self, health: HealthState) -> None:
        with self._lock:
            self._health = health

    def set_telemetry(self, **kw) -> None:
        with self._lock:
            self.telemetry.update(kw)

    def health_check(self) -> HealthState:
        with self._lock:
            return self._health if self._connected else HealthState.FAULT

    def send_command(self, command: str,
                     priority: CommandPriority = CommandPriority.NORMAL) -> None:
        with self._lock:
            if not self._connected:
                raise DeviceError(f"{self.name}: not connected")
            self.commands.append(command)


class DeviceRegistry:
    """Thread-safe registry of devices keyed by name."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, Device] = {}

    def register(self, device: Device) -> None:
        if not isinstance(device, Device):
            raise DeviceError(
                f"object '{type(device).__name__}' is not a Device")
        with self._lock:
            if device.name in self._devices:
                raise DeviceError(f"duplicate device '{device.name}'")
            self._devices[device.name] = device
        log.info("registered device '%s' (%s)", device.name,
                 device.device_type.value)

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._devices.pop(name, None) is not None

    def get(self, name: str) -> Device:
        with self._lock:
            device = self._devices.get(name)
        if device is None:
            raise DeviceNotFound(name)
        return device

    def find(self, name: str) -> Device | None:
        with self._lock:
            return self._devices.get(name)

    def by_type(self, device_type: DeviceType) -> list[Device]:
        with self._lock:
            return [d for d in self._devices.values()
                    if d.device_type == device_type]

    def all(self) -> list[Device]:
        with self._lock:
            return list(self._devices.values())

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._devices)
