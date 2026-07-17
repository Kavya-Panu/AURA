"""
intent/confidence.py
====================
Confidence thresholds and banding, exactly per the spec:

    > 0.90       EXECUTE            immediate execution
    0.70 - 0.90  EXECUTE_LOG        execute and log confidence
    0.40 - 0.70  CLARIFY            ask a clarification question
    < 0.40       UNKNOWN            fall back to UNKNOWN intent
"""
from __future__ import annotations

from enum import Enum, auto

EXECUTE_THRESHOLD: float = 0.90
LOG_THRESHOLD: float = 0.70
CLARIFY_THRESHOLD: float = 0.40


class ConfidenceLevel(Enum):
    EXECUTE = auto()
    EXECUTE_LOG = auto()
    CLARIFY = auto()
    UNKNOWN = auto()


def level(confidence: float) -> ConfidenceLevel:
    """Map a raw 0..1 confidence to its action band."""
    if confidence > EXECUTE_THRESHOLD:
        return ConfidenceLevel.EXECUTE
    if confidence >= LOG_THRESHOLD:
        return ConfidenceLevel.EXECUTE_LOG
    if confidence >= CLARIFY_THRESHOLD:
        return ConfidenceLevel.CLARIFY
    return ConfidenceLevel.UNKNOWN
