"""
hardware/led_driver.py
======================
LedDriver controls status/RGB LEDs by sending commands THROUGH the
HardwareManager. Supports brightness, color, blink, fade, pulse, an idle-lighting
preset, and a charging indicator. Time-based effects (blink/fade/pulse) run on a
background thread and are cancellable; the driver never touches serial itself.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from core.logger import get_logger

from .device_types import CommandPriority, DeviceType
from .face_driver import CommandSink

log = get_logger("hardware.led")


@dataclass(frozen=True)
class Color:
    """An RGB color (0..255 per channel)."""
    r: int = 0
    g: int = 0
    b: int = 0

    def clamped(self) -> "Color":
        c = lambda v: max(0, min(255, int(v)))
        return Color(c(self.r), c(self.g), c(self.b))

    def scaled(self, factor: float) -> "Color":
        return Color(int(self.r * factor), int(self.g * factor),
                     int(self.b * factor)).clamped()

    def token(self) -> str:
        c = self.clamped()
        return f"{c.r},{c.g},{c.b}"


# A few named colors for presets.
OFF = Color(0, 0, 0)
WHITE = Color(255, 255, 255)
GREEN = Color(0, 255, 0)
AMBER = Color(255, 140, 0)
BLUE = Color(0, 120, 255)


class LedDriver:
    """Drives a named LED channel via the HardwareManager. Thread-safe."""

    device_type = DeviceType.LED

    def __init__(self, send: CommandSink, channel: str = "led",
                 device_name: str = "esp32",
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._send = send
        self._channel = channel
        self._device = device_name
        self._clock = clock
        self._sleep = sleep

        self._lock = threading.RLock()
        self._color = OFF
        self._brightness = 1.0
        self._effect_thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def color(self) -> Color:
        with self._lock:
            return self._color

    @property
    def brightness(self) -> float:
        with self._lock:
            return self._brightness

    # ---------------------------------------------------- static control
    def set_color(self, color: Color, *,
                  priority: CommandPriority = CommandPriority.NORMAL) -> None:
        self._stop_effect()
        with self._lock:
            self._color = color.clamped()
            effective = self._color.scaled(self._brightness)
        self._route(f"LED:{self._channel}:{effective.token()}", priority)

    def set_brightness(self, level: float) -> None:
        with self._lock:
            self._brightness = max(0.0, min(1.0, level))
            effective = self._color.scaled(self._brightness)
        self._route(f"LED:{self._channel}:{effective.token()}",
                    CommandPriority.NORMAL)

    def off(self) -> None:
        self.set_color(OFF)

    # ---------------------------------------------------- presets
    def idle(self) -> None:
        """Calm idle lighting (dim blue)."""
        self._stop_effect()
        with self._lock:
            self._brightness = 0.3
            self._color = BLUE
            effective = self._color.scaled(self._brightness)
        self._route(f"LED:{self._channel}:{effective.token()}",
                    CommandPriority.LOW)

    def charging_indicator(self) -> None:
        """Pulsing amber to indicate charging."""
        self.pulse(AMBER, period_s=1.5)

    # ---------------------------------------------------- effects (threaded)
    def blink(self, color: Color, *, times: int = 3, period_s: float = 0.4) -> None:
        on = color
        def run() -> None:
            for _ in range(times):
                if self._cancel.is_set():
                    break
                self._emit_direct(on)
                self._sleep(period_s / 2)
                if self._cancel.is_set():
                    break
                self._emit_direct(OFF)
                self._sleep(period_s / 2)
        self._start_effect(run)

    def fade(self, target: Color, *, duration_s: float = 1.0, steps: int = 20) -> None:
        with self._lock:
            start = self._color
        def run() -> None:
            for i in range(1, steps + 1):
                if self._cancel.is_set():
                    break
                f = i / steps
                mixed = Color(int(start.r + (target.r - start.r) * f),
                              int(start.g + (target.g - start.g) * f),
                              int(start.b + (target.b - start.b) * f))
                self._emit_direct(mixed)
                self._sleep(duration_s / steps)
            with self._lock:
                self._color = target.clamped()
        self._start_effect(run)

    def pulse(self, color: Color, *, period_s: float = 1.5, cycles: int = 0) -> None:
        """Breathing pulse. cycles=0 => until cancelled."""
        def run() -> None:
            steps = 20
            count = 0
            while not self._cancel.is_set():
                for i in list(range(steps)) + list(range(steps, 0, -1)):
                    if self._cancel.is_set():
                        break
                    self._emit_direct(color.scaled(i / steps))
                    self._sleep(period_s / (2 * steps))
                count += 1
                if cycles and count >= cycles:
                    break
        self._start_effect(run)

    def stop_effect(self) -> None:
        self._stop_effect()

    # ------------------------------------------------------------- internal
    def _start_effect(self, run: Callable[[], None]) -> None:
        self._stop_effect()
        self._cancel.clear()
        self._effect_thread = threading.Thread(
            target=run, name=f"led-{self._channel}", daemon=True)
        self._effect_thread.start()

    def _stop_effect(self) -> None:
        self._cancel.set()
        thread = self._effect_thread
        if thread is not None and thread.is_alive() and \
                thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._effect_thread = None

    def _emit_direct(self, color: Color) -> None:
        self._route(f"LED:{self._channel}:{color.clamped().token()}",
                    CommandPriority.LOW)

    def _route(self, command: str, priority: CommandPriority) -> None:
        self._send(self._device, command, priority=priority)
        log.debug("led -> %s (%s)", command, priority.name)
