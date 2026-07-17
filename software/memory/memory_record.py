"""
memory/memory_record.py
=======================
The core memory data types: MemoryType, Importance, and the MemoryRecord
dataclass. New memory types are added by extending the MemoryType enum - nothing
else needs to change (Open/Closed).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable


class MemoryType(Enum):
    """Kinds of memory AURA stores. Extend here to add new types."""
    USER_PROFILE = "user_profile"
    CONVERSATION = "conversation"          # conversation history
    STUDY_SESSION = "study_session"
    FOCUS_SESSION = "focus_session"
    QUIZ_RESULT = "quiz_result"
    HOMEWORK_PROGRESS = "homework_progress"
    TRANSLATION_PREF = "translation_pref"
    PREFERENCE = "preference"              # general user preferences
    ACHIEVEMENT = "achievement"
    FACT = "fact"                          # long-term facts about the user/world
    TEMPORARY_CONTEXT = "temporary_context"  # short-term conversational context


class Importance(Enum):
    """Importance levels drive retention. Ordered: higher value = more important."""
    TEMPORARY = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class MemoryRecord:
    """One stored memory. Immutable; updates produce a new record via `evolve`.

    Fields:
        memory_id: Unique id.
        memory_type: What kind of memory this is.
        content: The remembered content (arbitrary JSON-able dict).
        importance: Retention priority.
        confidence: 0..1 how much AURA trusts this memory.
        created_at / updated_at: Unix timestamps.
        expires_at: Unix timestamp after which the memory is expired, or None
            for no explicit expiry (retention still applies by importance).
        tags: Free-form tags for search.
        metadata: Free-form extra data (source, usage counters, ...).
    """
    memory_type: MemoryType
    content: dict[str, Any]
    importance: Importance = Importance.MEDIUM
    confidence: float = 1.0
    memory_id: str = field(default_factory=_new_id)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    expires_at: float | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, *, now: float | None = None) -> bool:
        now = now if now is not None else _now()
        return self.expires_at is not None and now >= self.expires_at

    def age_s(self, *, now: float | None = None) -> float:
        now = now if now is not None else _now()
        return max(0.0, now - self.created_at)

    def evolve(self, *, clock: Callable[[], float] = _now, **changes: Any) -> "MemoryRecord":
        """Return an updated copy with a refreshed `updated_at`."""
        changes.setdefault("updated_at", clock())
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "importance": self.importance.name,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "tags": list(self.tags),
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "MemoryRecord":
        return MemoryRecord(
            memory_id=data["memory_id"],
            memory_type=MemoryType(data["memory_type"]),
            content=dict(data.get("content", {})),
            importance=Importance[data.get("importance", "MEDIUM")],
            confidence=float(data.get("confidence", 1.0)),
            created_at=float(data["created_at"]),
            updated_at=float(data["updated_at"]),
            expires_at=(None if data.get("expires_at") is None
                        else float(data["expires_at"])),
            tags=tuple(data.get("tags", ())),
            metadata=dict(data.get("metadata", {})),
        )
