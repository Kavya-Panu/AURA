"""
memory/memory_search.py
=======================
Search over memory records: keyword, tag, type, time-range and importance
filters, combined and scored. Operates on a list of records supplied by the
Memory Manager (which owns the provider), so search is decoupled from storage.

A `semantic_hook` is accepted for a future vector/embedding search: when set, it
can re-rank or supply candidates. Until then, search is deterministic keyword +
metadata matching - fast and dependency-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .memory_config import SearchConfig
from .memory_record import Importance, MemoryRecord, MemoryType


@dataclass
class SearchQuery:
    """A memory search request. All fields optional; combine freely."""
    text: str | None = None                 # keyword(s), matched in content/tags
    tags: tuple[str, ...] = ()
    memory_type: MemoryType | None = None
    min_importance: Importance | None = None
    created_after: float | None = None
    created_before: float | None = None
    limit: int | None = None


@dataclass(frozen=True)
class SearchHit:
    record: MemoryRecord
    score: float


# A future semantic search hook: (query_text, candidates) -> {memory_id: score}.
SemanticHook = Callable[[str, list[MemoryRecord]], dict[str, float]]


class MemorySearch:
    """Filters and scores memory records for a query."""

    def __init__(self, config: SearchConfig | None = None,
                 semantic_hook: SemanticHook | None = None) -> None:
        self._cfg = config or SearchConfig()
        self._semantic = semantic_hook

    def search(self, records: list[MemoryRecord], query: SearchQuery,
               *, now: float | None = None) -> list[SearchHit]:
        candidates = [r for r in records if self._matches(r, query, now)]

        # Score: keyword overlap + tag overlap + importance + recency.
        semantic_scores: dict[str, float] = {}
        if self._semantic is not None and query.text:
            try:
                semantic_scores = self._semantic(query.text, candidates)
            except Exception:                           # noqa: BLE001
                semantic_scores = {}

        hits: list[SearchHit] = []
        for record in candidates:
            score = self._score(record, query, semantic_scores.get(record.memory_id))
            if score >= self._cfg.min_score:
                hits.append(SearchHit(record, score))

        hits.sort(key=lambda h: h.score, reverse=True)
        limit = self._resolve_limit(query.limit)
        return hits[:limit]

    # ------------------------------------------------------------- matching
    def _matches(self, r: MemoryRecord, q: SearchQuery,
                 now: float | None) -> bool:
        if q.memory_type is not None and r.memory_type != q.memory_type:
            return False
        if q.min_importance is not None and \
                r.importance.value < q.min_importance.value:
            return False
        if q.created_after is not None and r.created_at < q.created_after:
            return False
        if q.created_before is not None and r.created_at > q.created_before:
            return False
        if q.tags and not set(q.tags).issubset(set(r.tags)):
            return False
        if q.text:
            if not self._text_match(r, q.text):
                return False
        return True

    def _text_match(self, r: MemoryRecord, text: str) -> bool:
        terms = [t for t in text.lower().split() if t]
        haystack = self._haystack(r)
        return any(term in haystack for term in terms)

    def _haystack(self, r: MemoryRecord) -> str:
        parts = [str(v) for v in r.content.values()]
        parts.extend(r.tags)
        parts.append(r.memory_type.value)
        return " ".join(parts).lower()

    # -------------------------------------------------------------- scoring
    def _score(self, r: MemoryRecord, q: SearchQuery,
               semantic: float | None) -> float:
        score = 0.0
        if q.text:
            terms = [t for t in q.text.lower().split() if t]
            haystack = self._haystack(r)
            score += sum(1.0 for t in terms if t in haystack)
        if q.tags:
            score += len(set(q.tags) & set(r.tags))
        score += 0.25 * r.importance.value          # prefer important memories
        score += 0.5 * r.confidence
        if semantic is not None:
            score += 2.0 * semantic                 # semantic dominates when present
        return score

    def _resolve_limit(self, limit: int | None) -> int:
        if limit is None:
            return self._cfg.default_limit
        return max(1, min(limit, self._cfg.max_limit))
