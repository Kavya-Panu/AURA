"""
memory/memory_summary.py
========================
The MemorySummary service summarizes groups of MemoryRecords into a single,
concise summary MemoryRecord - reducing storage while preserving important
facts.

Strict boundaries (by design):
    * It NEVER calls an LLM directly.
    * It NEVER stores or deletes memories.
    * It NEVER touches a storage provider.
It only receives MemoryRecord objects and returns a summarized MemoryRecord.

Pluggability: the actual text/content reduction is delegated to a
`SummaryStrategy` (dependency injection). A deterministic `HeuristicSummary`
ships by default (no AI, no network). An LLM-backed strategy can be dropped in
later WITHOUT changing this interface - e.g. an adapter whose callable routes to
the Brain Manager. The MemorySummary service itself remains reasoning-free.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from core.logger import get_logger

from .memory_config import SummarizationConfig
from .memory_exceptions import MemoryValidationError
from .memory_record import Importance, MemoryRecord, MemoryType

log = get_logger("memory.summary")


@runtime_checkable
class SummaryStrategy(Protocol):
    """Reduces a group of records to a summary content dict. Implementations may
    be heuristic (default) or LLM-backed (injected later). A strategy must be
    pure with respect to storage: it only reads the records it is given."""

    name: str

    def summarize(self, records: list[MemoryRecord]) -> dict: ...


class HeuristicSummary:
    """Deterministic, non-AI summary strategy. Aggregates records without any
    reasoning: counts, time span, merged tags, importance profile, and a compact
    per-record digest capped to keep the summary small. This is the safe default
    and the fallback if no smarter strategy is injected."""

    name = "heuristic"

    def __init__(self, max_digest_items: int = 20) -> None:
        self._max_digest = max_digest_items

    def summarize(self, records: list[MemoryRecord]) -> dict:
        earliest = min(r.created_at for r in records)
        latest = max(r.updated_at for r in records)
        tags: set[str] = set()
        importance_counts: dict[str, int] = {}
        for r in records:
            tags.update(r.tags)
            importance_counts[r.importance.name] = (
                importance_counts.get(r.importance.name, 0) + 1)

        # Compact digest: keep the highest-importance / most-recent items first.
        ordered = sorted(
            records, key=lambda r: (r.importance.value, r.updated_at),
            reverse=True)
        digest = [self._digest_one(r) for r in ordered[:self._max_digest]]

        return {
            "summary": f"{len(records)} memories summarized",
            "count": len(records),
            "from": earliest,
            "to": latest,
            "tags": sorted(tags),
            "importance_counts": importance_counts,
            "digest": digest,
            "truncated": len(records) > self._max_digest,
        }

    @staticmethod
    def _digest_one(r: MemoryRecord) -> dict:
        # A tiny, storage-free projection of one record.
        preview = {k: r.content[k] for k in list(r.content)[:4]}
        return {"id": r.memory_id, "type": r.memory_type.value,
                "importance": r.importance.name, "content": preview}


class CallableSummaryStrategy:
    """Adapts any ``Callable[[list[MemoryRecord]], dict]`` into a SummaryStrategy.

    This is the seam for a future LLM summarizer: wrap a callable that (for
    example) asks the Brain Manager to summarize, and inject it here. The
    MemorySummary service stays unchanged and never calls the LLM itself - the
    reasoning lives entirely inside the injected callable, outside this module.
    """

    def __init__(self, fn: Callable[[list[MemoryRecord]], dict],
                 name: str = "callable") -> None:
        self._fn = fn
        self.name = name

    def summarize(self, records: list[MemoryRecord]) -> dict:
        result = self._fn(records)
        if not isinstance(result, dict):
            raise MemoryValidationError(
                "summary strategy must return a dict content")
        return result


@dataclass(frozen=True)
class SummaryOutcome:
    """The product of a summarization: the new summary record plus the ids of the
    records it summarized (so the caller - MemoryManager - can decide to replace
    them; this service never deletes anything itself)."""
    summary: MemoryRecord
    source_ids: tuple[str, ...]


class MemorySummary:
    """Summarizes groups of MemoryRecords into a single summary MemoryRecord.

    Thread-safe and storage-free. Returns records; it does not persist them.
    """

    def __init__(self, config: SummarizationConfig | None = None,
                 strategy: SummaryStrategy | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        import time
        self._cfg = config or SummarizationConfig()
        self._strategy = strategy or HeuristicSummary()
        self._clock = clock or time.time
        self._lock = threading.RLock()

    @property
    def strategy_name(self) -> str:
        return self._strategy.name

    def set_strategy(self, strategy: SummaryStrategy) -> None:
        """Swap the summary strategy at runtime (e.g. heuristic -> LLM-backed)."""
        with self._lock:
            self._strategy = strategy
        log.info("summary strategy changed -> %s", strategy.name)

    def can_summarize(self, records: list[MemoryRecord]) -> bool:
        """True if the group is large enough to be worth summarizing."""
        return (self._cfg.enabled and
                len(records) >= self._cfg.min_records_to_summarize)

    # ------------------------------------------------------------------ core
    def summarize(self, records: list[MemoryRecord], *,
                  memory_type: MemoryType | None = None,
                  importance: Importance = Importance.HIGH,
                  force: bool = False) -> SummaryOutcome | None:
        """Summarize a group of records into one summary MemoryRecord.

        Returns a SummaryOutcome (summary record + source ids), or None if there
        is nothing to summarize or the group is below the configured threshold
        (unless `force`). Never stores or deletes anything.
        """
        if not records:
            return None
        if not force and not self.can_summarize(records):
            return None

        mtype = memory_type or self._dominant_type(records)
        with self._lock:
            content = self._strategy.summarize(records)

        now = self._clock()
        summary = MemoryRecord(
            memory_type=mtype,
            content=content,
            importance=importance,
            confidence=self._aggregate_confidence(records),
            created_at=now,
            updated_at=now,
            expires_at=None,                     # summaries are long-lived
            tags=("summary",),
            metadata={"summary": True,
                      "strategy": self._strategy.name,
                      "summarized_count": len(records)})
        source_ids = tuple(r.memory_id for r in records)
        log.info("summarized %d %s records via %s", len(records),
                 mtype.value, self._strategy.name)
        return SummaryOutcome(summary=summary, source_ids=source_ids)

    # ---- convenience wrappers for the spec's named cases ----
    def summarize_conversation(self, records: list[MemoryRecord],
                               **kw) -> SummaryOutcome | None:
        return self.summarize(records, memory_type=MemoryType.CONVERSATION, **kw)

    def summarize_study_sessions(self, records: list[MemoryRecord],
                                 **kw) -> SummaryOutcome | None:
        return self.summarize(records, memory_type=MemoryType.STUDY_SESSION, **kw)

    def summarize_focus_sessions(self, records: list[MemoryRecord],
                                 **kw) -> SummaryOutcome | None:
        return self.summarize(records, memory_type=MemoryType.FOCUS_SESSION, **kw)

    def summarize_quiz_history(self, records: list[MemoryRecord],
                               **kw) -> SummaryOutcome | None:
        return self.summarize(records, memory_type=MemoryType.QUIZ_RESULT, **kw)

    def compress_low_importance(self, records: list[MemoryRecord],
                                **kw) -> SummaryOutcome | None:
        """Compress many low-importance memories into one concise summary. The
        summary itself is kept at MEDIUM so it survives longer than the LOW
        originals it replaces."""
        low = [r for r in records if r.importance.value <= Importance.LOW.value]
        if not low:
            return None
        return self.summarize(low, importance=Importance.MEDIUM, **kw)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _dominant_type(records: list[MemoryRecord]) -> MemoryType:
        counts: dict[MemoryType, int] = {}
        for r in records:
            counts[r.memory_type] = counts.get(r.memory_type, 0) + 1
        return max(counts, key=counts.get)

    @staticmethod
    def _aggregate_confidence(records: list[MemoryRecord]) -> float:
        return round(sum(r.confidence for r in records) / len(records), 4)
