"""
memory/memory_retention.py
==========================
The MemoryRetention service decides what to KEEP, ARCHIVE, SUMMARIZE, or REMOVE
for each memory, based on importance, age, usage and confidence. It ONLY makes
decisions - it never deletes, archives, or stores anything itself. It returns a
list of RetentionAction objects that the MemoryManager can execute.

Policy (defaults, all configurable via memory_config.RetentionPolicy plus the
additive DecisionPolicy below):
    CRITICAL  -> KEEP forever (never removed)
    HIGH      -> KEEP indefinitely
    MEDIUM    -> SUMMARIZE after a configurable period
    LOW       -> ARCHIVE after a configurable period
    TEMPORARY -> EXPIRE (REMOVE) once past its TTL / age

Because it returns actions rather than performing them, retention stays testable,
side-effect-free, and decoupled from storage.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

from core.logger import get_logger

from .memory_config import RetentionPolicy
from .memory_record import Importance, MemoryRecord, MemoryType

log = get_logger("memory.retention")


class RetentionAction(Enum):
    """What retention recommends for a memory."""
    KEEP = auto()
    ARCHIVE = auto()
    SUMMARIZE = auto()
    REMOVE = auto()


@dataclass
class DecisionPolicy:
    """Additive knobs for retention decisions (does not modify RetentionPolicy).

    Ages are in seconds. Confidence below the floor makes a memory eligible for
    removal one tier sooner. `usage_key` names the metadata counter that records
    how often a memory has been retrieved (0 if absent); frequently-used
    memories are kept even past their age threshold.
    """
    medium_summarize_after_s: float = 60 * 60 * 24 * 30    # ~30 days
    low_archive_after_s: float = 60 * 60 * 24 * 14         # ~14 days
    low_remove_after_s: float = 60 * 60 * 24 * 60          # ~60 days (post-archive)
    confidence_floor: float = 0.2
    usage_key: str = "use_count"
    keep_if_used_at_least: int = 5                         # sticky if reused a lot


@dataclass(frozen=True)
class RetentionDecision:
    """One decision for one memory."""
    memory_id: str
    action: RetentionAction
    reason: str
    memory_type: MemoryType


@dataclass
class RetentionReport:
    """The full set of decisions from one evaluation pass."""
    decisions: list[RetentionDecision] = field(default_factory=list)

    def of(self, action: RetentionAction) -> list[RetentionDecision]:
        return [d for d in self.decisions if d.action == action]

    @property
    def to_remove(self) -> list[str]:
        return [d.memory_id for d in self.of(RetentionAction.REMOVE)]

    @property
    def to_archive(self) -> list[str]:
        return [d.memory_id for d in self.of(RetentionAction.ARCHIVE)]

    @property
    def to_summarize(self) -> list[str]:
        return [d.memory_id for d in self.of(RetentionAction.SUMMARIZE)]

    def counts(self) -> dict[str, int]:
        out = {a.name: 0 for a in RetentionAction}
        for d in self.decisions:
            out[d.action.name] += 1
        return out


class MemoryRetention:
    """Computes retention actions for memories. Decision-only; no side effects."""

    def __init__(self, retention_policy: RetentionPolicy | None = None,
                 decision_policy: DecisionPolicy | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        import time
        self._retention = retention_policy or RetentionPolicy()
        self._policy = decision_policy or DecisionPolicy()
        self._clock = clock or time.time
        self._lock = threading.RLock()

    def decide(self, record: MemoryRecord, *,
               now: float | None = None) -> RetentionDecision:
        """Decide the action for a single memory."""
        now = now if now is not None else self._clock()
        with self._lock:
            action, reason = self._evaluate(record, now)
        return RetentionDecision(memory_id=record.memory_id, action=action,
                                 reason=reason, memory_type=record.memory_type)

    def evaluate(self, records: list[MemoryRecord], *,
                 now: float | None = None) -> RetentionReport:
        """Decide actions for a batch, returning a RetentionReport."""
        now = now if now is not None else self._clock()
        report = RetentionReport()
        for r in records:
            report.decisions.append(self.decide(r, now=now))
        return report

    # ------------------------------------------------------------ internal
    def _evaluate(self, r: MemoryRecord, now: float) -> tuple[RetentionAction, str]:
        # Explicit hard expiry always wins (temporary/short-lived memories).
        if r.is_expired(now=now):
            return RetentionAction.REMOVE, "past expires_at"

        # Frequently reused memories are sticky regardless of age.
        if self._use_count(r) >= self._policy.keep_if_used_at_least:
            return RetentionAction.KEEP, "frequently used"

        age = r.age_s(now=now)
        low_confidence = r.confidence < self._policy.confidence_floor

        if r.importance == Importance.CRITICAL:
            return RetentionAction.KEEP, "critical: never delete"

        if r.importance == Importance.HIGH:
            return RetentionAction.KEEP, "high: keep indefinitely"

        if r.importance == Importance.MEDIUM:
            if age >= self._policy.medium_summarize_after_s:
                return RetentionAction.SUMMARIZE, "medium aged past summarize window"
            return RetentionAction.KEEP, "medium within window"

        if r.importance == Importance.LOW:
            if age >= self._policy.low_remove_after_s or low_confidence:
                return RetentionAction.REMOVE, (
                    "low & very old" if not low_confidence
                    else "low & low-confidence")
            if age >= self._policy.low_archive_after_s:
                return RetentionAction.ARCHIVE, "low aged past archive window"
            return RetentionAction.KEEP, "low within window"

        # TEMPORARY without a hard expiry: remove once older than its TTL.
        ttl = self._retention.temporary_ttl_s
        if ttl > 0 and age >= ttl:
            return RetentionAction.REMOVE, "temporary aged past ttl"
        return RetentionAction.KEEP, "temporary within ttl"

    def _use_count(self, r: MemoryRecord) -> int:
        try:
            return int(r.metadata.get(self._policy.usage_key, 0))
        except (TypeError, ValueError):
            return 0
