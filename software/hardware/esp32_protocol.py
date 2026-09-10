"""
hardware/esp32_protocol.py
==========================
Single source of truth for translating AURA's laptop-side hardware commands to
the line protocol implemented by the current ESP32 face firmware.

The ESP32 accepts one newline-terminated command at a time, including:

    HAPPY
    THINK
    LOOK LEFT
    BLINK
    DOUBLE_BLINK
    BOOK START
    BOOK STOP
    BRIGHTNESS 180
    PING
    STATUS

Keeping this mapping here prevents the Python brain and the firmware vocabulary
from drifting apart.
"""
from __future__ import annotations


# Laptop-side tokens -> current firmware tokens.
_EMOTION_ALIASES: dict[str, str] = {
    "NORMAL": "NEUTRAL",
    "NEUTRAL": "NEUTRAL",
    "HAPPY": "HAPPY",
    "EXCITED": "EXCITED",
    "SAD": "SAD",
    "ANGRY": "ANGRY",
    "SURPRISED": "SURPRISED",
    "CONFUSED": "CONFUSED",
    "CURIOUS": "CURIOUS",
    "LOVE": "LOVE",
    "THINK": "THINK",
    "THINKING": "THINK",
    "LISTEN": "LISTEN",
    "LISTENING": "LISTEN",
    "SEARCH": "SEARCH",
    "SEARCHING": "SEARCH",
    "WORRIED": "WORRIED",
    "CELEBRATE": "CELEBRATE",
    "SLEEPY": "SLEEPY",
    "SLEEP": "SLEEP",
    "ERROR": "ERROR",
}


def emotion_command(token: str) -> str:
    """Return the firmware token for an emotion.

    Known AURA aliases are normalized. Unknown non-empty tokens are passed
    through in uppercase for forward compatibility with future firmware
    emotions.
    """
    normalized = str(token).strip().upper()
    if normalized.startswith("FACE "):
        normalized = normalized[5:].strip()
    if not normalized:
        raise ValueError("emotion token cannot be empty")
    return _EMOTION_ALIASES.get(normalized, normalized)


def gaze_command(x: float, y: float, dead_zone: float = 0.25) -> str:
    """Convert normalized continuous gaze into the firmware's five directions."""
    x = max(-1.0, min(1.0, float(x)))
    y = max(-1.0, min(1.0, float(y)))

    if abs(x) < dead_zone and abs(y) < dead_zone:
        return "LOOK CENTER"
    if abs(x) >= abs(y):
        return "LOOK RIGHT" if x > 0 else "LOOK LEFT"
    return "LOOK DOWN" if y > 0 else "LOOK UP"


def blink_command(times: int = 1) -> str:
    """Map one blink or multiple requested blinks to supported firmware verbs."""
    return "BLINK" if int(times) <= 1 else "DOUBLE_BLINK"


def focus_command(enabled: bool) -> str:
    return "BOOK START" if enabled else "BOOK STOP"


def brightness_command(level: int) -> str:
    value = max(0, min(255, int(level)))
    return f"BRIGHTNESS {value}"


def timer_start_command(seconds: int, kind: str = "timer") -> str:
    value = max(1, min(2_678_400, int(seconds)))
    category = str(kind).strip().upper()
    if category not in {"TIMER", "ALARM", "REMINDER", "FOCUS"}:
        category = "TIMER"
    return f"TIMER START {value} {category}"


def timer_alert_command(kind: str = "timer") -> str:
    category = str(kind).strip().upper()
    if category not in {"TIMER", "ALARM", "REMINDER", "FOCUS"}:
        category = "TIMER"
    return f"TIMER ALERT {category}"


def timer_stop_command() -> str:
    return "TIMER STOP"
