"""
memory/memory_context.py
========================
MemoryContext is AURA's current WORKING memory - runtime state only. It tracks
the active conversation/session, recently retrieved/stored memories, a small
in-RAM LRU cache of records, the current provider name, cache statistics, and the
timestamps of the last cleanup/summary passes.

It is runtime state only: it NEVER persists anything and never touches a storage
provider. The MemoryManager updates it as operations happen; other modules can
read a thread-safe snapshot. Bounded structures keep memory usage low.
"""
from __future__ import annotations

import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Callable

from core.logger import get_logger

from .memory_record import MemoryRecord

log = get_logger("memory.context")


@dataclass(frozen=True)
class CacheStats:
    """Snapshot of cache performance."""
    hits: int
    misses: int
    size: int
    capacity: int

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0


@dataclass(frozen=True)
class MemoryContextSnapshot:
    """Immutable point-in-time view of working memory."""
    conversation_id: str | None
    session_id: str | None
    provider: str | None
    recent_retrieved: tuple[str, ...]
    recent_stored: tuple[str, ...]
    cache: CacheStats
    last_cleanup_at: float | None
    last_summary_at: float | None
    updated_at: float


class MemoryContext:
    """Thread-safe runtime working memory. No persistence."""

    def __init__(self, cache_capacity: int = 128, recent_capacity: int = 32,
                 clock: Callable[[], float] | None = None) -> None:
        import time
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()

        self._conversation_id: str | None = None
        self._session_id: str | None = None
        self._provider: str | None = None

        self._recent_retrieved: deque[str] = deque(maxlen=recent_capacity)
        self._recent_stored: deque[str] = deque(maxlen=recent_capacity)

        self._cache: "OrderedDict[str, MemoryRecord]" = OrderedDict()
        self._cache_capacity = cache_capacity
        self._hits = 0
        self._misses = 0

        self._last_cleanup_at: float | None = None
        self._last_summary_at: float | None = None

    # --------------------------------------------------- session / provider
    def set_conversation(self, conversation_id: str | None) -> None:
        with self._lock:
            self._conversation_id = conversation_id

    def set_session(self, session_id: str | None) -> None:
        with self._lock:
            self._session_id = session_id

    def set_provider(self, provider_name: str | None) -> None:
        with self._lock:
            self._provider = provider_name

    @property
    def conversation_id(self) -> str | None:
        with self._lock:
            return self._conversation_id

    @property
    def session_id(self) -> str | None:
        with self._lock:
            return self._session_id

    @property
    def provider(self) -> str | None:
        with self._lock:
            return self._provider

    # ------------------------------------------------------ recent activity
    def record_retrieved(self, record: MemoryRecord) -> None:
        with self._lock:
            self._recent_retrieved.append(record.memory_id)
            self._cache_put(record)

    def record_stored(self, record: MemoryRecord) -> None:
        with self._lock:
            self._recent_stored.append(record.memory_id)
            self._cache_put(record)

    def recent_retrieved(self) -> list[str]:
        with self._lock:
            return list(self._recent_retrieved)

    def recent_stored(self) -> list[str]:
        with self._lock:
            return list(self._recent_stored)

    # ------------------------------------------------------- active cache
    def cache_get(self, memory_id: str) -> MemoryRecord | None:
        """Look up a record in the working cache, updating hit/miss stats and
        LRU order. Returns None on a miss (the manager then hits the provider)."""
        with self._lock:
            record = self._cache.get(memory_id)
            if record is None:
                self._misses += 1
                return None
            self._cache.move_to_end(memory_id)
            self._hits += 1
            return record

    def cache_put(self, record: MemoryRecord) -> None:
        with self._lock:
            self._cache_put(record)

    def cache_invalidate(self, memory_id: str) -> None:
        with self._lock:
            self._cache.pop(memory_id, None)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _cache_put(self, record: MemoryRecord) -> None:
        """LRU insert. Caller holds the lock."""
        self._cache[record.memory_id] = record
        self._cache.move_to_end(record.memory_id)
        while len(self._cache) > self._cache_capacity:
            self._cache.popitem(last=False)

    def cache_stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(hits=self._hits, misses=self._misses,
                              size=len(self._cache),
                              capacity=self._cache_capacity)

    # ------------------------------------------------- maintenance markers
    def mark_cleanup(self, when: float | None = None) -> None:
        with self._lock:
            self._last_cleanup_at = when if when is not None else self._clock()

    def mark_summary(self, when: float | None = None) -> None:
        with self._lock:
            self._last_summary_at = when if when is not None else self._clock()

    @property
    def last_cleanup_at(self) -> float | None:
        with self._lock:
            return self._last_cleanup_at

    @property
    def last_summary_at(self) -> float | None:
        with self._lock:
            return self._last_summary_at

    # ------------------------------------------------------------ snapshot
    def snapshot(self) -> MemoryContextSnapshot:
        with self._lock:
            return MemoryContextSnapshot(
                conversation_id=self._conversation_id,
                session_id=self._session_id,
                provider=self._provider,
                recent_retrieved=tuple(self._recent_retrieved),
                recent_stored=tuple(self._recent_stored),
                cache=CacheStats(hits=self._hits, misses=self._misses,
                                 size=len(self._cache),
                                 capacity=self._cache_capacity),
                last_cleanup_at=self._last_cleanup_at,
                last_summary_at=self._last_summary_at,
                updated_at=self._clock())

    def reset(self) -> None:
        """Clear all runtime state (e.g. on a new user session). Persists nothing
        because there is nothing persisted - this only drops in-RAM state."""
        with self._lock:
            self._conversation_id = None
            self._session_id = None
            self._recent_retrieved.clear()
            self._recent_stored.clear()
            self._cache.clear()
            self._hits = 0
            self._misses = 0
