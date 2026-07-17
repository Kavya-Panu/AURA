"""
brain/conversation_context.py
=============================
A single conversation's rolling state: history, current topic, mode, and recent
questions. Thread-safe; bounded to a configurable number of turns so memory and
prompt size stay controlled.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    role: str            # "user" | "assistant"
    content: str


class ConversationContext:
    """Rolling conversation state for one session."""

    def __init__(self, max_turns: int = 12) -> None:
        self._lock = threading.RLock()
        self._turns: deque[Turn] = deque(maxlen=max_turns * 2)  # user+assistant
        self._topic: str = ""
        self._mode: str | None = None
        self._recent_questions: deque[str] = deque(maxlen=max_turns)

    def add_user(self, content: str) -> None:
        with self._lock:
            self._turns.append(Turn("user", content))
            self._recent_questions.append(content)

    def add_assistant(self, content: str) -> None:
        with self._lock:
            self._turns.append(Turn("assistant", content))

    def set_topic(self, topic: str) -> None:
        with self._lock:
            self._topic = topic

    def set_mode(self, mode: str | None) -> None:
        with self._lock:
            self._mode = mode

    def messages(self) -> list[dict[str, str]]:
        """History as provider-ready messages."""
        with self._lock:
            return [{"role": t.role, "content": t.content} for t in self._turns]

    @property
    def topic(self) -> str:
        with self._lock:
            return self._topic

    @property
    def mode(self) -> str | None:
        with self._lock:
            return self._mode

    def recent_questions(self) -> list[str]:
        with self._lock:
            return list(self._recent_questions)

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()
            self._recent_questions.clear()
            self._topic = ""
