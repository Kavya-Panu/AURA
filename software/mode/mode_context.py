"""
mode/mode_context.py
====================
Thread-safe record of the current mode and everything attached to it: previous
mode, when it was entered, who requested it and why, and the mode's typed
parameters. Perception/voice/AI threads may read it concurrently; ``snapshot()``
returns an immutable copy for lock-free reasoning.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .mode_types import ModeParams, ModeType, make_default_params


@dataclass(frozen=True)
class ModeSnapshot:
    """Immutable point-in-time view of the mode context."""
    current: ModeType
    previous: ModeType | None
    entered_at: float
    elapsed_s: float
    requested_by: str
    reason: str
    params: ModeParams
    extra: dict[str, Any]


class ModeContext:
    """Mutable, lock-guarded mode record."""

    def __init__(self, initial: ModeType = ModeType.NORMAL) -> None:
        self._lock = threading.RLock()
        self._current = initial
        self._previous: ModeType | None = None
        self._entered_at = time.monotonic()
        self._requested_by = "system"
        self._reason = "startup"
        self._params: ModeParams = make_default_params(initial)
        self._extra: dict[str, Any] = {}

    # ------------------------------------------------------------- mutation
    def set_mode(self, mode: ModeType, params: ModeParams,
                 requested_by: str, reason: str) -> None:
        """Record a completed transition into ``mode``."""
        with self._lock:
            self._previous = self._current
            self._current = mode
            self._params = params
            self._requested_by = requested_by
            self._reason = reason
            self._entered_at = time.monotonic()
            self._extra = {}

    def update_params(self, **fields: Any) -> None:
        """Patch fields on the current params object (e.g. quiz score)."""
        with self._lock:
            for key, value in fields.items():
                if hasattr(self._params, key):
                    setattr(self._params, key, value)
                else:
                    self._extra[key] = value

    def set_extra(self, key: str, value: Any) -> None:
        with self._lock:
            self._extra[key] = value

    # ---------------------------------------------------------------- reads
    @property
    def current(self) -> ModeType:
        with self._lock:
            return self._current

    @property
    def previous(self) -> ModeType | None:
        with self._lock:
            return self._previous

    def elapsed(self) -> float:
        """Seconds spent in the current mode."""
        with self._lock:
            return time.monotonic() - self._entered_at

    def snapshot(self) -> ModeSnapshot:
        with self._lock:
            return ModeSnapshot(
                current=self._current,
                previous=self._previous,
                entered_at=self._entered_at,
                elapsed_s=time.monotonic() - self._entered_at,
                requested_by=self._requested_by,
                reason=self._reason,
                params=self._params,
                extra=dict(self._extra),
            )
