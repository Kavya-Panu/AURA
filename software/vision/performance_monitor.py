"""
vision/performance_monitor.py
=============================
Collects Vision performance statistics for debugging and Jetson optimization:
camera FPS, processing FPS, per-detector execution time, dropped frames, queue
latency, and CPU usage (GPU hooks left for the future). Thread-safe; pure
measurement - it changes nothing about robot behaviour.

Detectors/pipeline feed it timings via :meth:`record_detector_time` and
:meth:`record_processed_frame`; it reads dropped-frame counts straight from the
FrameBuffer. :meth:`snapshot` returns an immutable stats view.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class DetectorStats:
    """Timing stats for one detector (milliseconds)."""
    name: str
    last_ms: float
    avg_ms: float
    max_ms: float
    samples: int


@dataclass(frozen=True)
class PerformanceSnapshot:
    """Immutable point-in-time performance view."""
    camera_fps: float
    processing_fps: float
    dropped_frames: int
    queue_latency_ms: float
    cpu_percent: float
    gpu_percent: float | None
    detectors: tuple[DetectorStats, ...]
    updated_at: float


class PerformanceMonitor:
    """Aggregates Vision timing metrics. Thread-safe."""

    def __init__(self, window: int = 120,
                 clock: Callable[[], float] = time.monotonic,
                 cpu_sampler: Callable[[], float] | None = None) -> None:
        self._clock = clock
        self._cpu_sampler = cpu_sampler or _default_cpu_sampler
        self._lock = threading.RLock()
        self._window = window

        self._proc_times: deque[float] = deque(maxlen=window)
        self._det_samples: dict[str, deque[float]] = {}
        self._det_last: dict[str, float] = {}
        self._det_max: dict[str, float] = {}
        self._camera_fps = 0.0
        self._dropped = 0
        self._queue_latency_ms = 0.0

    # ---------------------------------------------------------- recording
    def record_camera_fps(self, fps: float) -> None:
        with self._lock:
            self._camera_fps = max(0.0, fps)

    def record_processed_frame(self, latency_ms: float = 0.0) -> None:
        """Call once per fully-processed frame (drives processing FPS)."""
        now = self._clock()
        with self._lock:
            self._proc_times.append(now)
            if latency_ms:
                self._queue_latency_ms = latency_ms

    def record_detector_time(self, name: str, elapsed_ms: float) -> None:
        with self._lock:
            samples = self._det_samples.setdefault(name, deque(maxlen=self._window))
            samples.append(elapsed_ms)
            self._det_last[name] = elapsed_ms
            self._det_max[name] = max(self._det_max.get(name, 0.0), elapsed_ms)

    def record_dropped(self, dropped_total: int) -> None:
        with self._lock:
            self._dropped = dropped_total

    # ------------------------------------------------------------ compute
    def _processing_fps(self) -> float:
        if len(self._proc_times) < 2:
            return 0.0
        span = self._proc_times[-1] - self._proc_times[0]
        return (len(self._proc_times) - 1) / span if span > 0 else 0.0

    def snapshot(self) -> PerformanceSnapshot:
        with self._lock:
            detectors = tuple(
                DetectorStats(
                    name=name,
                    last_ms=round(self._det_last.get(name, 0.0), 3),
                    avg_ms=round(sum(s) / len(s), 3) if s else 0.0,
                    max_ms=round(self._det_max.get(name, 0.0), 3),
                    samples=len(s))
                for name, s in sorted(self._det_samples.items()))
            return PerformanceSnapshot(
                camera_fps=round(self._camera_fps, 2),
                processing_fps=round(self._processing_fps(), 2),
                dropped_frames=self._dropped,
                queue_latency_ms=round(self._queue_latency_ms, 3),
                cpu_percent=round(self._cpu_sampler(), 1),
                gpu_percent=None,                 # future: NVML on Jetson
                detectors=detectors,
                updated_at=self._clock())

    def as_dict(self) -> dict:
        s = self.snapshot()
        return {
            "camera_fps": s.camera_fps,
            "processing_fps": s.processing_fps,
            "dropped_frames": s.dropped_frames,
            "queue_latency_ms": s.queue_latency_ms,
            "cpu_percent": s.cpu_percent,
            "gpu_percent": s.gpu_percent,
            "detectors": {d.name: {"last_ms": d.last_ms, "avg_ms": d.avg_ms,
                                   "max_ms": d.max_ms, "samples": d.samples}
                          for d in s.detectors},
        }


def _default_cpu_sampler() -> float:
    """Best-effort CPU percent. Uses psutil if present, else 0.0 (never raises,
    so importing this module needs no dependency)."""
    try:
        import psutil
        return float(psutil.cpu_percent(interval=None))
    except Exception:                                   # noqa: BLE001
        return 0.0
