"""
intent/intent_result.py
=======================
The Intent Engine's ONLY output: a structured IntentResult. Downstream systems
(Behavior Manager, Mode Manager) consume this - the engine itself never acts.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .intent_types import Intent


@dataclass(frozen=True)
class IntentResult:
    """Structured understanding of one utterance.

    Attributes:
        intent: The classified intent (Intent.UNKNOWN if unclassifiable).
        confidence: 0..1 matcher confidence.
        parameters: Extracted + validated parameters.
        missing_parameters: Required parameters not found in the utterance.
        clarification_needed: True when AURA should ask a follow-up question.
        clarification_question: The question to speak (empty if not needed).
        response_hint: Short hint for downstream response phrasing.
        raw_text: The original, unmodified input text.
        timestamp: time.time() at classification.
    """
    intent: Intent
    confidence: float
    parameters: dict[str, Any] = field(default_factory=dict)
    missing_parameters: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str = ""
    response_hint: str = ""
    raw_text: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form for logging / event payloads."""
        return {
            "intent": self.intent.value,
            "confidence": round(self.confidence, 3),
            "parameters": dict(self.parameters),
            "missing_parameters": list(self.missing_parameters),
            "clarification_needed": self.clarification_needed,
            "clarification_question": self.clarification_question,
            "response_hint": self.response_hint,
            "raw_text": self.raw_text,
            "timestamp": self.timestamp,
        }
