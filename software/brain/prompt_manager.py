"""
brain/prompt_manager.py
=======================
Selects and builds the system prompt for a given mode. Prompts are external
(see system_prompts.py) and overridable/extendable at runtime, so new modes can
be supported without code changes (Open/Closed).
"""
from __future__ import annotations

import threading

from core.logger import get_logger

from .brain_exceptions import PromptError
from .system_prompts import DEFAULT_SYSTEM_PROMPTS

log = get_logger("brain.prompt")


class PromptManager:
    """Maps a mode name to a system prompt. Thread-safe; overridable."""

    def __init__(self, prompts: dict[str, str] | None = None) -> None:
        self._lock = threading.RLock()
        self._prompts: dict[str, str] = dict(DEFAULT_SYSTEM_PROMPTS)
        if prompts:
            self._prompts.update(prompts)

    def set_prompt(self, mode: str, prompt: str) -> None:
        """Add or override a mode's prompt at runtime (future modes supported)."""
        if not prompt.strip():
            raise PromptError("prompt must be non-empty")
        with self._lock:
            self._prompts[mode.upper()] = prompt

    def get_prompt(self, mode: str | None) -> str:
        """Return the system prompt for a mode, falling back to DEFAULT."""
        key = (mode or "DEFAULT").upper()
        with self._lock:
            return self._prompts.get(key, self._prompts["DEFAULT"])

    def modes(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._prompts))
