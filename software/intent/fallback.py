"""
intent/fallback.py
==================
Builders for the UNKNOWN fallback result (spec Appendix A: unclassifiable
input -> UNKNOWN, emotion CONFUSED, short reprompt; never guess a destructive
action).
"""
from __future__ import annotations

from .intent_result import IntentResult
from .intent_types import Intent

REPROMPT = "Sorry, could you rephrase that?"


def unknown_result(raw_text: str, confidence: float = 0.0) -> IntentResult:
    """The canonical UNKNOWN IntentResult."""
    return IntentResult(
        intent=Intent.UNKNOWN,
        confidence=confidence,
        parameters={"raw_text": raw_text},
        clarification_needed=True,
        clarification_question=REPROMPT,
        response_hint="confused",
        raw_text=raw_text,
    )
