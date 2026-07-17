"""
hardware/hardware_manager.py
============================
The HardwareManager is the ONLY module that talks to physical hardware. It owns
the SerialManager (ESP32 link) and a DeviceRegistry, runs a heartbeat/health
thread, and exposes a single API for other modules to send commands - so no
other module ever touches a port, servo, LED, propeller, or battery sensor.

It implements the core Module protocol (LifecycleManager owns it). It integrates
with the rest of AURA purely through the Event Bus:
  * SUBSCRIBES to EMOTION_CHANGED (emitted by Speech/Behavior) and forwards the
    emotion/mouth token to the ESP32 face - this is how software decisions become
    visible on the physical robot.
  * PUBLISHES HARDWARE_STARTED/STOPPED, DEVICE_CONNECTED/DISCONNECTED,
    SERIAL_CONNECTED/DISCONNECTED, COMMAND_SENT/RECEIVED, DEVICE_ERROR,
    BATTERY_LOW, HARDWARE_ERROR.

New hardware is added by registering a Device - the HardwareManager itself never
changes (Open/Closed).
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.event_bus import Event, EventBus
from core.logger import get_logger

from . import hardware_events as ev
from .device_registry import Device, DeviceRegistry, MockDevice, SerialDevice
from .device_types import (
    CommandPriority, ConnectionState, DeviceType, HealthState)
from .hardware_config import HardwareConfig
from .hardware_exceptions import DeviceNotFound, HardwareError
from .serial_manager import SerialManager, SerialTransport

log = get_logger("hardware.manager")

# Emotion tokens are single words; a mouth command carries a MOUTH:<shape> line.
_FACE_DEVICE = "esp32"


class HardwareManager:
    """Owns the serial link + devices; the sole boundary to physical hardware."""

    name = "hardware"

    def __init__(self, event_bus: EventBus, config: HardwareConfig,
                 transport: SerialTransport,
                 registry: DeviceRegistry | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._cfg = config
        self._registry = registry or DeviceRegistry()
        self._clock = clock

        self._serial = SerialManager(
            event_bus, config.serial, transport,
            on_line=self._on_serial_line, queue_max=config.queue.max_size,
            clock=clock)

        self._running = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._sub_ids: list[int] = []
        self._battery_warned = False

    # =====================================================================
    #  Module protocol
    # =====================================================================
    def initialize(self) -> None:
        # Register the ESP32 face device by default (driven over serial). Its
        # send path is injected from the SerialManager - the device never opens
        # a port itself.
        if self._registry.find(_FACE_DEVICE) is None:
            face = SerialDevice(_FACE_DEVICE, DeviceType.ESP32,
                                send=self._serial.send,
                                is_link_up=lambda: self._serial.connected)
            self._registry.register(face)
        log.info("hardware initialised (devices: %s)",
                 ", ".join(self._registry.names()))

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._serial.start()
        # connect all registered devices
        for device in self._registry.all():
            self._connect_device(device)
        # subscribe to face-driving events (only the HAL forwards these to HW)
        self._sub_ids.append(self._bus.subscribe(
            ev.EMOTION_CHANGED, self._on_emotion_changed, priority=50))
        # heartbeat / health thread
        if self._cfg.health.enabled:
            self._health_thread = threading.Thread(
                target=self._health_loop, name="hardware-heartbeat", daemon=True)
            self._health_thread.start()
        self._bus.emit(ev.HARDWARE_STARTED,
                       {"devices": list(self._registry.names())},
                       source=self.name)
        log.info("hardware started")

    def stop(self) -> None:
        self._running.clear()
        for sub in self._sub_ids:
            self._bus.unsubscribe(sub)
        self._sub_ids.clear()
        if self._health_thread is not None:
            self._health_thread.join(timeout=2.0)
            self._health_thread = None
        for device in self._registry.all():
            self._disconnect_device(device)
        self._serial.stop()
        self._bus.emit(ev.HARDWARE_STOPPED, {}, source=self.name)
        log.info("hardware stopped")

    def health_check(self) -> bool:
        # Healthy if every connected device reports non-FAULT.
        for device in self._registry.all():
            try:
                if device.is_connected() and device.health_check() == HealthState.FAULT:
                    return False
            except Exception:                           # noqa: BLE001
                return False
        return True

    # =====================================================================
    #  Device management (registration / discovery)
    # =====================================================================
    def register_device(self, device: Device) -> None:
        """Register a new device. If hardware is already running, connect it now.
        The HardwareManager needs no changes to support new device kinds."""
        self._registry.register(device)
        if self._running.is_set():
            self._connect_device(device)

    def unregister_device(self, name: str) -> bool:
        device = self._registry.find(name)
        if device is not None:
            self._disconnect_device(device)
        return self._registry.unregister(name)

    def discover_devices(self) -> dict:
        """Report currently registered devices, their type, connection and
        health - a snapshot for diagnostics/UemI."""
        out = {}
        for d in self._registry.all():
            out[d.name] = {
                "type": d.device_type.value,
                "connected": _safe(d.is_connected, False),
                "health": _safe(lambda: d.health_check().name, "UNKNOWN"),
            }
        return out

    @property
    def devices(self) -> tuple[str, ...]:
        return self._registry.names()

    @property
    def serial_state(self) -> ConnectionState:
        return self._serial.state

    def available_ports(self) -> list[str]:
        return self._serial.list_ports()

    # =====================================================================
    #  Commands (the single hardware entry point for other modules)
    # =====================================================================
    def send_command(self, device_name: str, command: str, *,
                     priority: CommandPriority = CommandPriority.NORMAL) -> None:
        """Send a raw command to a named device. Raises DeviceNotFound if the
        device isn't registered, or DeviceError on failure."""
        device = self._registry.get(device_name)
        try:
            device.send_command(command, priority)
        except HardwareError as exc:
            self._bus.emit(ev.DEVICE_ERROR,
                           {"device": device_name, "error": str(exc)},
                           source=self.name)
            raise

    def set_emotion(self, emotion_token: str) -> None:
        """Send an emotion token to the ESP32 face (convenience wrapper)."""
        self.send_command(_FACE_DEVICE, emotion_token,
                          priority=CommandPriority.HIGH)

    # =====================================================================
    #  Bus integration: forward EMOTION_CHANGED to the ESP32 face
    # =====================================================================
    def _on_emotion_changed(self, event: Event) -> None:
        # Speech/Behavior emit {"emotion": "<TOKEN>"} and mouth animation emits
        # {"mouth": "MOUTH_<SHAPE>"} on the same event; forward whichever is set.
        data = event.data or {}
        face = self._registry.find(_FACE_DEVICE)
        if face is None or not face.is_connected():
            return
        try:
            if "emotion" in data:
                face.send_command(str(data["emotion"]), CommandPriority.HIGH)
            elif "mouth" in data:
                face.send_command(f"MOUTH:{data['mouth']}", CommandPriority.NORMAL)
        except HardwareError as exc:
            self._bus.emit(ev.DEVICE_ERROR,
                           {"device": _FACE_DEVICE, "error": str(exc)},
                           source=self.name)

    def _on_serial_line(self, line: str) -> None:
        """Handle an inbound line from the ESP32 (telemetry/acks). Battery
        telemetry of the form 'BATTERY:<pct>' updates the battery device and may
        raise BATTERY_LOW."""
        if line.startswith("BATTERY:"):
            try:
                pct = float(line.split(":", 1)[1])
            except ValueError:
                return
            self._update_battery(pct)

    # =====================================================================
    #  Heartbeat / health monitoring
    # =====================================================================
    def _health_loop(self) -> None:
        interval = max(0.1, self._cfg.health.interval_s)
        while self._running.is_set():
            time.sleep(interval)
            if not self._running.is_set():
                break
            try:
                self._run_health_check()
            except Exception:                           # noqa: BLE001
                log.exception("health check pass failed")

    def _run_health_check(self) -> None:
        # heartbeat to the ESP32 (best-effort; failure triggers reconnect inside
        # the SerialManager)
        if self._serial.connected:
            self._serial.send(self._cfg.health.heartbeat_command,
                              CommandPriority.LOW)
        # poll device health; emit DEVICE_ERROR for any that faulted
        for device in self._registry.all():
            try:
                if device.is_connected() and \
                        device.health_check() == HealthState.FAULT:
                    self._bus.emit(ev.DEVICE_ERROR,
                                   {"device": device.name, "health": "FAULT"},
                                   source=self.name)
            except Exception as exc:                    # noqa: BLE001
                self._bus.emit(ev.HARDWARE_ERROR,
                               {"device": device.name, "error": str(exc)},
                               source=self.name)
        # battery from a mock battery device's telemetry, if present
        for battery in self._registry.by_type(DeviceType.BATTERY):
            pct = getattr(battery, "telemetry", {}).get("percent")
            if isinstance(pct, (int, float)):
                self._update_battery(float(pct))

    def _update_battery(self, percent: float) -> None:
        threshold = self._cfg.health.battery_low_threshold
        if percent <= threshold and not self._battery_warned:
            self._battery_warned = True
            self._bus.emit(ev.BATTERY_LOW, {"percent": percent},
                           source=self.name)
        elif percent > threshold:
            self._battery_warned = False

    # =====================================================================
    #  Helpers
    # =====================================================================
    def _connect_device(self, device: Device) -> None:
        try:
            device.connect()
            self._bus.emit(ev.DEVICE_CONNECTED,
                           {"device": device.name,
                            "type": device.device_type.value}, source=self.name)
        except Exception as exc:                        # noqa: BLE001
            self._bus.emit(ev.DEVICE_ERROR,
                           {"device": device.name, "error": str(exc)},
                           source=self.name)

    def _disconnect_device(self, device: Device) -> None:
        try:
            device.disconnect()
            self._bus.emit(ev.DEVICE_DISCONNECTED, {"device": device.name},
                           source=self.name)
        except Exception:                               # noqa: BLE001
            pass


def _safe(fn: Callable, default):
    try:
        return fn()
    except Exception:                                   # noqa: BLE001
        return default
