"""
brain/conversation_manager.py
=============================
Owns conversation sessions (keyed by id), each a bounded ConversationContext.
Thread-safe so simultaneous requests on different sessions don't interfere.
"""
from __future__ import annotations

import threading

from core.logger import get_logger

from .conversation_context import ConversationContext

log = get_logger("brain.conversation")


class ConversationManager:
    """Manages one or more conversation sessions."""

    DEFAULT_SESSION = "default"

    def __init__(self, max_turns: int = 12) -> None:
        self._lock = threading.RLock()
        self._max_turns = max_turns
        self._sessions: dict[str, ConversationContext] = {}

    def get(self, session_id: str = DEFAULT_SESSION) -> ConversationContext:
        with self._lock:
            ctx = self._sessions.get(session_id)
            if ctx is None:
                ctx = ConversationContext(self._max_turns)
                self._sessions[session_id] = ctx
            return ctx

    def reset(self, session_id: str = DEFAULT_SESSION) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].clear()

    def sessions(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sessions)
