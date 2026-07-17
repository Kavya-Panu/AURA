"""
intent/intent_context.py
========================
Conversation + session context the engine uses for follow-ups: last intent,
last parameters (e.g. subject inheritance: "teach me physics" ... "quiz me"
-> quiz on physics), and arbitrary session state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent_types import Intent

_MAX_HISTORY = 20


@dataclass
class IntentContext:
    """Mutable per-conversation context passed into IntentEngine.process()."""
    history: list[tuple[Intent, dict[str, Any]]] = field(default_factory=list)
    session_state: dict[str, Any] = field(default_factory=dict)

    def add(self, intent: Intent, parameters: dict[str, Any]) -> None:
        """Record a classified turn (bounded history)."""
        self.history.append((intent, dict(parameters)))
        if len(self.history) > _MAX_HISTORY:
            self.history.pop(0)

    @property
    def last_intent(self) -> Intent | None:
        return self.history[-1][0] if self.history else None

    @property
    def last_parameters(self) -> dict[str, Any]:
        return dict(self.history[-1][1]) if self.history else {}

    def last_value(self, key: str) -> Any | None:
        """Most recent value of ``key`` anywhere in history (newest first)."""
        for _, params in reversed(self.history):
            if key in params:
                return params[key]
        return None
