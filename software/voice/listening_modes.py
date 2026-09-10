"""Small, testable helpers for AURA's hands-free listening modes."""
from __future__ import annotations

import re

WAKE_PHRASES = ("hey aura", "okay aura", "ok aura", "aura")
STOP_PHRASES = (
    "aura stop",
    "aura shut up",
    "aura keep quiet",
)

# Common offline-ASR spellings of the name are accepted internally. The
# user-facing commands remain the three explicit "AURA ..." phrases above.
STOP_PHRASE_ALIASES = (
    "ora stop",
    "ora shut up",
    "ora keep quiet",
    "or a stop",
    "or a shut up",
    "or a keep quiet",
)


def is_stop_phrase(text: str) -> bool:
    """Return True only for an explicit AURA-addressed stop command."""
    normalized = re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()
    return normalized in (*STOP_PHRASES, *STOP_PHRASE_ALIASES)


def strip_wake_phrase(text: str) -> str | None:
    """Return the request following AURA's name, or None if not addressed."""
    cleaned = " ".join(text.strip().split())
    for phrase in WAKE_PHRASES:
        match = re.search(rf"\b{re.escape(phrase)}\b", cleaned, re.IGNORECASE)
        if match:
            return cleaned[match.end():].lstrip(" ,.!?:;-")
    return None
