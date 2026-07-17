"""
speech/speech_queue.py
======================
A thread-safe priority speech queue. Supports queued speech, priority messages
(lower number = higher priority, jumps ahead), interruption (a high-priority
item can request the current utterance be stopped), and cancellation (clear all).
"""
from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True)
class SpeechItem:
    """One queued utterance. Ordered by (priority, sequence) for a stable heap."""
    priority: int
    sequence: int
    text: str = field(compare=False)
    mode: str | None = field(compare=False, default=None)
    emotion_hint: str | None = field(compare=False, default=None)
    interrupt: bool = field(compare=False, default=False)
    metadata: dict[str, Any] = field(compare=False, default_factory=dict)


class SpeechQueue:
    """Bounded, thread-safe priority queue for utterances."""

    def __init__(self, maxsize: int = 32) -> None:
        self._lock = threading.RLock()
        self._not_empty = threading.Condition(self._lock)
        self._heap: list[SpeechItem] = []
        self._counter = itertools.count()
        self._maxsize = maxsize

    def put(self, text: str, *, priority: int = 100, mode: str | None = None,
            emotion_hint: str | None = None, interrupt: bool = False,
            metadata: dict | None = None) -> bool:
        """Enqueue an utterance. Returns False if the queue is full."""
        with self._lock:
            if len(self._heap) >= self._maxsize:
                return False
            item = SpeechItem(priority=priority, sequence=next(self._counter),
                              text=text, mode=mode, emotion_hint=emotion_hint,
                              interrupt=interrupt, metadata=metadata or {})
            heapq.heappush(self._heap, item)
            self._not_empty.notify()
            return True

    def get(self, timeout: float | None = None) -> SpeechItem | None:
        """Pop the highest-priority item, waiting up to timeout. None on timeout."""
        with self._not_empty:
            if not self._heap:
                if not self._not_empty.wait(timeout=timeout):
                    return None
            if not self._heap:
                return None
            return heapq.heappop(self._heap)

    def peek(self) -> SpeechItem | None:
        with self._lock:
            return self._heap[0] if self._heap else None

    def clear(self) -> int:
        """Cancel everything queued. Returns how many were removed."""
        with self._lock:
            n = len(self._heap)
            self._heap.clear()
            return n

    def __len__(self) -> int:
        with self._lock:
            return len(self._heap)

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return not self._heap
