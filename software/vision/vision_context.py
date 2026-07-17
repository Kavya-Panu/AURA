"""
vision/vision_context.py
========================
Thread-safe store of the Vision System's live state. The capture/processing
threads (future stages) will update it while other modules read it, so every
access goes through a lock and :meth:`snapshot` returns an immutable copy for
lock-free reasoning.

Holds exactly the fields the spec requires: vision enabled, camera connected,
capture FPS, processing FPS, active detectors, camera id, running state, and the
last error.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VisionSnapshot:
    """Immutable point-in-time view of the Vision context."""
    enabled: bool
    running: bool
    camera_connected: bool
    camera_id: int
    capture_fps: float
    processing_fps: float
    active_detectors: tuple[str, ...]
    last_error: str | None
    updated_at: float


class VisionContext:
    """Mutable, lock-guarded Vision state."""

    def __init__(self, camera_id: int = 0, enabled: bool = True) -> None:
        self._lock = threading.RLock()
        self._enabled = enabled
        self._running = False
        self._camera_connected = False
        self._camera_id = camera_id
        self._capture_fps = 0.0
        self._processing_fps = 0.0
        self._active_detectors: set[str] = set()
        self._last_error: str | None = None

    # ------------------------------------------------------------- mutation
    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled

    def set_running(self, running: bool) -> None:
        with self._lock:
            self._running = running

    def set_camera_connected(self, connected: bool) -> None:
        with self._lock:
            self._camera_connected = connected

    def set_camera_id(self, camera_id: int) -> None:
        with self._lock:
            self._camera_id = camera_id

    def set_capture_fps(self, fps: float) -> None:
        with self._lock:
            self._capture_fps = max(0.0, fps)

    def set_processing_fps(self, fps: float) -> None:
        with self._lock:
            self._processing_fps = max(0.0, fps)

    def add_detector(self, name: str) -> None:
        with self._lock:
            self._active_detectors.add(name)

    def remove_detector(self, name: str) -> None:
        with self._lock:
            self._active_detectors.discard(name)

    def set_active_detectors(self, names: set[str]) -> None:
        with self._lock:
            self._active_detectors = set(names)

    def set_error(self, message: str | None) -> None:
        with self._lock:
            self._last_error = message

    def clear_error(self) -> None:
        with self._lock:
            self._last_error = None

    # ---------------------------------------------------------------- reads
    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def camera_connected(self) -> bool:
        with self._lock:
            return self._camera_connected

    @property
    def active_detectors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active_detectors))

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def snapshot(self) -> VisionSnapshot:
        """Return an immutable copy for lock-free reasoning."""
        with self._lock:
            return VisionSnapshot(
                enabled=self._enabled,
                running=self._running,
                camera_connected=self._camera_connected,
                camera_id=self._camera_id,
                capture_fps=self._capture_fps,
                processing_fps=self._processing_fps,
                active_detectors=tuple(sorted(self._active_detectors)),
                last_error=self._last_error,
                updated_at=time.monotonic(),
            )
