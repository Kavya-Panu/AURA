"""
vision/frame_buffer.py
======================
A thread-safe, bounded, latest-frame buffer sitting between the camera capture
thread (single producer) and any number of detector threads (many consumers).

Design goals (from the Stage 2 spec):
* completely thread-safe,
* store only the newest frames (low latency beats completeness for live vision),
* drop the oldest frame when full so memory can never grow unbounded,
* timestamp every frame,
* support multiple independent consumers,
* minimise latency - a consumer that only ever wants "the latest frame" gets it
  in O(1) without copying pixel data.

The buffer stores :class:`Frame` objects. The pixel payload is an opaque object
(a numpy array on the real system); this module never imports numpy or OpenCV,
so it works anywhere and stays purely about buffering.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Frame:
    """One captured frame plus metadata.

    Attributes:
        data: Opaque pixel payload (a numpy ndarray on the real system).
        index: Monotonic capture index (0, 1, 2, ...).
        timestamp: ``time.monotonic()`` when the frame was captured.
        width / height: Frame dimensions in pixels (0 if unknown).
        camera_id: Which camera produced the frame.
    """
    data: Any
    index: int
    timestamp: float
    width: int = 0
    height: int = 0
    camera_id: int = 0

    @property
    def age_s(self) -> float:
        """Seconds since this frame was captured."""
        return time.monotonic() - self.timestamp


class FrameBuffer:
    """Bounded latest-frames buffer with O(1) latest-frame access.

    Multiple consumers can all read the latest frame concurrently. A consumer
    that wants to avoid re-processing the same frame passes the last index it
    saw to :meth:`get_latest` / :meth:`wait_for_frame`.
    """

    def __init__(self, max_frames: int = 2) -> None:
        if max_frames < 1:
            raise ValueError("max_frames must be >= 1")
        self._max = max_frames
        self._lock = threading.Lock()
        self._frames: deque[Frame] = deque(maxlen=max_frames)
        self._latest: Frame | None = None
        self._new_frame = threading.Condition(self._lock)
        self._dropped = 0
        self._pushed = 0

    # ------------------------------------------------------------- producer
    def push(self, frame: Frame) -> None:
        """Add a frame (producer side). O(1). Oldest is dropped when full."""
        with self._lock:
            if len(self._frames) == self._max:
                self._dropped += 1        # deque(maxlen) will evict the oldest
            self._frames.append(frame)
            self._latest = frame
            self._pushed += 1
            self._new_frame.notify_all()

    # ------------------------------------------------------------- consumers
    def get_latest(self, since_index: int | None = None) -> Frame | None:
        """Return the newest frame, or None.

        If ``since_index`` is given, returns the latest frame only when it is
        newer than ``since_index`` (else None) - so a consumer never reprocesses
        a frame it already handled.
        """
        with self._lock:
            latest = self._latest
            if latest is None:
                return None
            if since_index is not None and latest.index <= since_index:
                return None
            return latest

    def wait_for_frame(self, since_index: int | None = None,
                       timeout_s: float | None = None) -> Frame | None:
        """Block until a frame newer than ``since_index`` is available, or the
        timeout elapses. Returns the frame or None on timeout. This is the
        low-latency path: a detector wakes the instant a new frame arrives."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        with self._lock:
            while True:
                latest = self._latest
                if latest is not None and (
                        since_index is None or latest.index > since_index):
                    return latest
                remaining = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                if not self._new_frame.wait(timeout=remaining):
                    return None       # timed out

    def snapshot(self) -> tuple[Frame, ...]:
        """Return all buffered frames, oldest first (copy of the container)."""
        with self._lock:
            return tuple(self._frames)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
            self._latest = None

    # -------------------------------------------------------------- metrics
    @property
    def size(self) -> int:
        with self._lock:
            return len(self._frames)

    @property
    def capacity(self) -> int:
        return self._max

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def pushed_count(self) -> int:
        with self._lock:
            return self._pushed

    @property
    def latest_index(self) -> int:
        with self._lock:
            return self._latest.index if self._latest is not None else -1
