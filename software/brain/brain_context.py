"""
brain/brain_context.py
======================
Thread-safe snapshot of the Brain's live state: current provider, whether a
request is in flight, counters, and the last error. Read by other modules;
written by the Brain Manager.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BrainSnapshot:
    current_provider: str | None
    busy: bool
    total_requests: int
    total_failures: int
    last_error: str | None
    updated_at: float


class BrainContext:
    """Mutable, lock-guarded Brain state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current_provider: str | None = None
        self._busy = False
        self._total_requests = 0
        self._total_failures = 0
        self._last_error: str | None = None

    def set_provider(self, name: str | None) -> None:
        with self._lock:
            self._current_provider = name

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            self._busy = busy

    def record_request(self) -> None:
        with self._lock:
            self._total_requests += 1

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._total_failures += 1
            self._last_error = error

    @property
    def current_provider(self) -> str | None:
        with self._lock:
            return self._current_provider

    def snapshot(self) -> BrainSnapshot:
        with self._lock:
            return BrainSnapshot(
                current_provider=self._current_provider,
                busy=self._busy,
                total_requests=self._total_requests,
                total_failures=self._total_failures,
                last_error=self._last_error,
                updated_at=time.monotonic(),
            )
