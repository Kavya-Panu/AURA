"""
hardware/battery_monitor.py
===========================
BatteryMonitor tracks battery percentage, charging state, voltage and a coarse
health estimate, and publishes BATTERY_LOW / BATTERY_CHARGING / BATTERY_FULL /
BATTERY_OK on the Event Bus. It is fed telemetry (from the HardwareManager's
inbound serial parsing or a battery device) via `update()`; it never reads a
sensor directly. Thread-safe; edge-triggered so events fire on state changes only.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

log = get_logger("hardware.battery")


class ChargeState(Enum):
    UNKNOWN = auto()
    DISCHARGING = auto()
    CHARGING = auto()
    FULL = auto()


class BatteryHealth(Enum):
    UNKNOWN = auto()
    GOOD = auto()
    FAIR = auto()
    POOR = auto()


@dataclass(frozen=True)
class BatteryStatus:
    percent: float
    charging: bool
    charge_state: str
    voltage: float | None
    health: str


class BatteryMonitor:
    """Edge-triggered battery state tracker + event publisher. Thread-safe."""

    def __init__(self, event_bus: EventBus, *,
                 low_threshold: float = 20.0, full_threshold: float = 99.0,
                 clock: Callable[[], float] | None = None) -> None:
        import time
        self._bus = event_bus
        self._low = low_threshold
        self._full = full_threshold
        self._clock = clock or time.monotonic

        self._lock = threading.RLock()
        self._percent = 100.0
        self._charging = False
        self._voltage: float | None = None
        self._charge_state = ChargeState.UNKNOWN
        # edge-tracking flags
        self._warned_low = False
        self._announced_charging = False
        self._announced_full = False

    def update(self, *, percent: float | None = None,
               charging: bool | None = None,
               voltage: float | None = None) -> None:
        """Feed new telemetry; emits events on state transitions only."""
        with self._lock:
            if percent is not None:
                self._percent = max(0.0, min(100.0, percent))
            if charging is not None:
                self._charging = charging
            if voltage is not None:
                self._voltage = voltage
            pct = self._percent
            chg = self._charging
            self._charge_state = self._derive_state(pct, chg)
            events = self._transitions(pct, chg)
        for event, data in events:
            self._bus.emit(event, data, source="hardware.battery")

    def _derive_state(self, pct: float, charging: bool) -> ChargeState:
        if charging:
            return ChargeState.FULL if pct >= self._full else ChargeState.CHARGING
        return ChargeState.DISCHARGING

    def _transitions(self, pct: float, charging: bool) -> list[tuple[RobotEvent, dict]]:
        events: list[tuple[RobotEvent, dict]] = []

        # Charging edge.
        if charging and not self._announced_charging:
            self._announced_charging = True
            events.append((RobotEvent.BATTERY_CHARGING, {"percent": pct}))
        if not charging:
            self._announced_charging = False

        # Full edge (while charging / at rest near 100).
        if pct >= self._full and not self._announced_full:
            self._announced_full = True
            events.append((RobotEvent.BATTERY_FULL, {"percent": pct}))
        if pct < self._full:
            self._announced_full = False

        # Low edge (only when discharging).
        if pct <= self._low and not charging and not self._warned_low:
            self._warned_low = True
            events.append((RobotEvent.BATTERY_LOW, {"percent": pct}))
        if pct > self._low or charging:
            if self._warned_low:
                # recovered from low
                events.append((RobotEvent.BATTERY_OK, {"percent": pct}))
            self._warned_low = False

        return events

    # ------------------------------------------------------------- status
    def _health(self) -> BatteryHealth:
        v = self._voltage
        if v is None:
            return BatteryHealth.UNKNOWN
        if v >= 3.7:
            return BatteryHealth.GOOD
        if v >= 3.4:
            return BatteryHealth.FAIR
        return BatteryHealth.POOR

    @property
    def percent(self) -> float:
        with self._lock:
            return self._percent

    @property
    def charging(self) -> bool:
        with self._lock:
            return self._charging

    def status(self) -> BatteryStatus:
        with self._lock:
            return BatteryStatus(
                percent=self._percent, charging=self._charging,
                charge_state=self._charge_state.name, voltage=self._voltage,
                health=self._health().name)
