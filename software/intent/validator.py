"""
intent/validator.py
===================
Parameter validation + repair, per the spec's Parameter Dictionary: durations
clamped to [15, 240] minutes, timers to [1, 86400] s, difficulty canonicalised,
languages checked against the known set, question counts bounded. Invalid,
unrepairable values are dropped (so a clarification can be asked) rather than
raising - the engine never crashes on user speech.
"""
from __future__ import annotations

from typing import Any

from core.logger import get_logger

from .intent_types import Intent
from .synonym_dictionary import DIFFICULTY, LANGUAGES

log = get_logger("intent.validator")

DURATION_MIN, DURATION_MAX = 15, 240
BREAK_MIN, BREAK_MAX = 1, 60
TIMER_MIN, TIMER_MAX = 1, 86_400
QCOUNT_MIN, QCOUNT_MAX = 1, 50

_KNOWN_LANGUAGES = set(LANGUAGES.values())


def validate(intent: Intent, params: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned copy of ``params`` (invalid values repaired/dropped)."""
    out: dict[str, Any] = {}
    for key, value in params.items():
        try:
            cleaned = _validate_one(key, value)
        except (TypeError, ValueError):
            log.debug("dropped invalid param %s=%r for %s",
                      key, value, intent.value)
            continue
        if cleaned is not None:
            out[key] = cleaned
    return out


def _validate_one(key: str, value: Any) -> Any | None:
    if key == "duration_minutes":
        v = int(value)
        return max(DURATION_MIN, min(DURATION_MAX, v))
    if key == "break_minutes":
        v = int(value)
        return max(BREAK_MIN, min(BREAK_MAX, v))
    if key == "timer_seconds":
        v = int(value)
        return v if TIMER_MIN <= v <= TIMER_MAX else max(
            TIMER_MIN, min(TIMER_MAX, v))
    if key == "question_count":
        v = int(value)
        return max(QCOUNT_MIN, min(QCOUNT_MAX, v))
    if key in ("source_language", "target_language"):
        name = str(value).strip().title()
        return name if name in _KNOWN_LANGUAGES else None
    if key == "difficulty":
        return DIFFICULTY.get(str(value).lower())
    if key in ("bidirectional", "continuous", "auto_detect_language",
               "phone_detection"):
        return bool(value)
    if key in ("progress",):
        v = float(value)
        return max(0.0, min(1.0, v))
    # Free-text params pass through trimmed.
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value
