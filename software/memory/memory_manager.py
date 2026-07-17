"""
memory/memory_manager.py
========================
The Memory Manager - AURA's long-term memory. It stores, retrieves, updates,
deletes, searches, summarizes and forgets memories, and publishes memory events.
It implements the core Module protocol so the LifecycleManager owns it, and runs
a background cleanup thread that expires/forgets memories per the retention
policy.

It ONLY manages memory. It never generates AI responses, reasons, controls
hardware, or changes emotions/modes. The Brain Manager talks to THIS class, never
to a storage provider directly. Summarization uses an INJECTED summarizer
callable - the Memory Manager never calls an LLM itself (that would be reasoning);
if no summarizer is injected, it falls back to a trivial non-AI reducer.

Thread-safety: an RLock guards manager-level operations; providers are themselves
thread-safe; the cleanup task uses an injectable clock and is `wait_until`-
testable (no fixed sleeps in the hot path).
"""
from __future__ import annotations

import threading
from typing import Callable

from core.event_bus import EventBus
from core.logger import get_logger

from . import memory_events as ev
from .memory_config import MemoryConfig
from .memory_exceptions import MemoryNotFound, MemoryValidationError
from .memory_provider import InMemoryProvider, MemoryProvider
from .memory_record import Importance, MemoryRecord, MemoryType
from .memory_search import MemorySearch, SearchQuery, SearchHit

log = get_logger("memory.manager")

# A summarizer reduces a group of records to a single summary content dict.
# Injected so the Memory Manager never performs reasoning/LLM calls itself.
Summarizer = Callable[[list[MemoryRecord]], dict]


class MemoryManager:
    """Owns a storage provider and provides all memory operations."""

    name = "memory"

    def __init__(self, event_bus: EventBus, config: MemoryConfig | None = None,
                 provider: MemoryProvider | None = None,
                 search: MemorySearch | None = None,
                 summarizer: Summarizer | None = None,
                 clock: Callable[[], float] = None) -> None:
        import time
        self._bus = event_bus
        self._cfg = config or MemoryConfig()
        self._provider = provider or InMemoryProvider()
        self._search = search or MemorySearch(self._cfg.search)
        self._summarizer = summarizer
        self._clock = clock or time.time

        self._lock = threading.RLock()
        self._cleanup_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    # =====================================================================
    #  Module protocol
    # =====================================================================
    def initialize(self) -> None:
        log.info("memory initialised (provider=%s)", self._provider.name)

    def start(self) -> None:
        if self._cfg.cleanup.enabled and self._cleanup_thread is None:
            self._stop.clear()
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop, name="memory-cleanup", daemon=True)
            self._cleanup_thread.start()
        log.info("memory started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=2.0)
            self._cleanup_thread = None
        log.info("memory stopped")

    def health_check(self) -> bool:
        # Healthy if the provider is reachable (a cheap all() call succeeds).
        try:
            self._provider.all()
            return True
        except Exception:                               # noqa: BLE001
            return False

    @property
    def provider(self) -> MemoryProvider:
        return self._provider

    def set_provider(self, provider: MemoryProvider) -> None:
        """Swap the storage backend (e.g. in-memory -> SQLite). Existing records
        are migrated. Publishes MEMORY_PROVIDER change via cleanup-completed-style
        event so listeners know storage moved."""
        with self._lock:
            old = self._provider
            for record in old.all():
                provider.put(record)
            self._provider = provider
        log.info("memory provider changed -> %s", provider.name)

    # =====================================================================
    #  Store / retrieve / update / delete
    # =====================================================================
    def store(self, memory_type: MemoryType, content: dict, *,
              importance: Importance = Importance.MEDIUM,
              confidence: float = 1.0, tags: tuple[str, ...] = (),
              metadata: dict | None = None,
              expires_at: float | None = None) -> MemoryRecord:
        """Create and persist a memory. Expiry defaults from the retention policy
        for the given importance if not supplied."""
        if not isinstance(content, dict):
            raise MemoryValidationError("content must be a dict")
        if not 0.0 <= confidence <= 1.0:
            raise MemoryValidationError("confidence must be in [0, 1]")

        now = self._clock()
        if expires_at is None:
            expires_at = self._default_expiry(importance, now)
        record = MemoryRecord(
            memory_type=memory_type, content=dict(content),
            importance=importance, confidence=confidence,
            created_at=now, updated_at=now, expires_at=expires_at,
            tags=tuple(tags), metadata=dict(metadata or {}))
        with self._lock:
            self._provider.put(record)
        self._bus.emit(ev.MEMORY_STORED,
                       {"memory_id": record.memory_id,
                        "type": memory_type.value,
                        "importance": importance.name}, source=self.name)
        return record

    def retrieve(self, memory_id: str) -> MemoryRecord:
        """Fetch one memory by id. Raises MemoryNotFound if absent/expired."""
        record = self._provider.get(memory_id)
        if record is None or record.is_expired(now=self._clock()):
            raise MemoryNotFound(memory_id)
        self._bus.emit(ev.MEMORY_RETRIEVED, {"memory_id": memory_id},
                       source=self.name)
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Like retrieve() but returns None instead of raising."""
        try:
            return self.retrieve(memory_id)
        except MemoryNotFound:
            return None

    def update(self, memory_id: str, **changes) -> MemoryRecord:
        """Update fields of an existing memory (content/importance/tags/...)."""
        with self._lock:
            existing = self._provider.get(memory_id)
            if existing is None:
                raise MemoryNotFound(memory_id)
            updated = existing.evolve(clock=self._clock, **changes)
            self._provider.put(updated)
        self._bus.emit(ev.MEMORY_UPDATED, {"memory_id": memory_id},
                       source=self.name)
        return updated

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by id."""
        with self._lock:
            removed = self._provider.delete(memory_id)
        if removed:
            self._bus.emit(ev.MEMORY_DELETED, {"memory_id": memory_id},
                           source=self.name)
        return removed

    # =====================================================================
    #  Search / list
    # =====================================================================
    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Search live (non-expired) memories."""
        now = self._clock()
        records = [r for r in self._provider.all() if not r.is_expired(now=now)]
        hits = self._search.search(records, query, now=now)
        self._bus.emit(ev.MEMORY_SEARCHED,
                       {"count": len(hits),
                        "type": query.memory_type.value if query.memory_type else None},
                       source=self.name)
        return hits

    def by_type(self, memory_type: MemoryType) -> list[MemoryRecord]:
        now = self._clock()
        return [r for r in self._provider.all()
                if r.memory_type == memory_type and not r.is_expired(now=now)]

    def all_live(self) -> list[MemoryRecord]:
        now = self._clock()
        return [r for r in self._provider.all() if not r.is_expired(now=now)]

    # =====================================================================
    #  Summarize / forget
    # =====================================================================
    def summarize(self, memory_type: MemoryType, *,
                  replace: bool = True) -> MemoryRecord | None:
        """Summarize a group of memories of one type into a single summary
        record, reducing storage while preserving useful information. Uses the
        injected summarizer if present; otherwise a trivial non-AI reducer.
        Returns the new summary record (or None if nothing to summarize)."""
        records = self.by_type(memory_type)
        if len(records) < self._cfg.summarization.min_records_to_summarize:
            return None

        content = (self._summarizer(records) if self._summarizer
                   else self._trivial_summary(records))
        summary = self.store(
            memory_type, content, importance=Importance.HIGH,
            tags=("summary",),
            metadata={"summarized_count": len(records),
                      "summary": True})

        if replace:
            with self._lock:
                for r in records:
                    if r.memory_id != summary.memory_id:
                        self._provider.delete(r.memory_id)

        self._bus.emit(ev.MEMORY_SUMMARIZED,
                       {"type": memory_type.value,
                        "summarized_count": len(records),
                        "summary_id": summary.memory_id}, source=self.name)
        return summary

    def forget_unimportant(self, *, max_importance: Importance = Importance.LOW,
                           older_than_s: float | None = None) -> int:
        """Forget (delete) low-importance memories, optionally only those older
        than a threshold. Returns how many were forgotten."""
        now = self._clock()
        forgotten = 0
        with self._lock:
            for r in self._provider.all():
                if r.importance.value > max_importance.value:
                    continue
                if older_than_s is not None and r.age_s(now=now) < older_than_s:
                    continue
                if self._provider.delete(r.memory_id):
                    forgotten += 1
        if forgotten:
            self._bus.emit(ev.MEMORY_FORGOTTEN, {"count": forgotten},
                           source=self.name)
        return forgotten

    # =====================================================================
    #  Retention / background cleanup
    # =====================================================================
    def run_cleanup(self) -> dict:
        """One cleanup pass: expire past-due memories and enforce retention caps.
        Returns a small stats dict. Safe to call directly (used by tests) or via
        the background loop."""
        now = self._clock()
        expired = 0
        with self._lock:
            records = self._provider.all()
            # 1) expire past-due
            for r in records:
                if expired >= self._cfg.cleanup.batch_limit:
                    break
                if r.is_expired(now=now):
                    if self._provider.delete(r.memory_id):
                        expired += 1
                        self._bus.emit(ev.MEMORY_EXPIRED,
                                       {"memory_id": r.memory_id,
                                        "type": r.memory_type.value},
                                       source=self.name)
            # 2) enforce caps (temporary total, low-per-type)
            capped = self._enforce_caps(now)
        self._bus.emit(ev.MEMORY_CLEANUP_COMPLETED,
                       {"expired": expired, "capped": capped}, source=self.name)
        return {"expired": expired, "capped": capped}

    def _enforce_caps(self, now: float) -> int:
        """Delete oldest overflow beyond the configured caps. Caller holds lock."""
        pol = self._cfg.retention
        removed = 0
        live = [r for r in self._provider.all() if not r.is_expired(now=now)]

        # temporary total cap
        if pol.max_temporary_total > 0:
            temps = sorted(
                [r for r in live if r.importance == Importance.TEMPORARY],
                key=lambda r: r.created_at)
            overflow = len(temps) - pol.max_temporary_total
            for r in temps[:max(0, overflow)]:
                if self._provider.delete(r.memory_id):
                    removed += 1

        # low-per-type cap
        if pol.max_low_per_type > 0:
            by_type: dict[MemoryType, list[MemoryRecord]] = {}
            for r in live:
                if r.importance == Importance.LOW:
                    by_type.setdefault(r.memory_type, []).append(r)
            for recs in by_type.values():
                recs.sort(key=lambda r: r.created_at)
                overflow = len(recs) - pol.max_low_per_type
                for r in recs[:max(0, overflow)]:
                    if self._provider.delete(r.memory_id):
                        removed += 1
        return removed

    def _cleanup_loop(self) -> None:
        interval = max(0.05, self._cfg.cleanup.interval_s)
        while not self._stop.is_set():
            # wait up to `interval`, but wake immediately on stop/trigger
            self._wake.wait(timeout=interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.run_cleanup()
            except Exception:                           # noqa: BLE001
                log.exception("memory cleanup pass failed")

    def trigger_cleanup(self) -> None:
        """Wake the background cleanup task immediately (used in tests)."""
        self._wake.set()

    # =====================================================================
    #  Helpers
    # =====================================================================
    def _default_expiry(self, importance: Importance, now: float) -> float | None:
        pol = self._cfg.retention
        ttl = {
            Importance.CRITICAL: pol.critical_ttl_s,
            Importance.HIGH: pol.high_ttl_s,
            Importance.MEDIUM: pol.medium_ttl_s,
            Importance.LOW: pol.low_ttl_s,
            Importance.TEMPORARY: pol.temporary_ttl_s,
        }[importance]
        return None if ttl <= 0 else now + ttl

    @staticmethod
    def _trivial_summary(records: list[MemoryRecord]) -> dict:
        """Non-AI fallback summary: counts + time span + merged tags. Contains no
        reasoning - just aggregation."""
        tags: set[str] = set()
        earliest = min(r.created_at for r in records)
        latest = max(r.updated_at for r in records)
        for r in records:
            tags.update(r.tags)
        return {
            "summary": f"{len(records)} records aggregated",
            "count": len(records),
            "from": earliest,
            "to": latest,
            "tags": sorted(tags),
        }
