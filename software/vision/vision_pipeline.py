"""
vision/vision_pipeline.py
=========================
The VisionPipeline orchestrates a set of detectors over the shared FrameBuffer,
merges their per-frame :class:`VisionResult`s into one combined result, feeds the
:class:`PerformanceMonitor`, and publishes ``PIPELINE_STARTED`` /
``PIPELINE_STOPPED`` / ``PIPELINE_ERROR``.

Two important design points:
* **Detectors stay autonomous.** The detectors built in earlier stages already
  run their own threads off the FrameBuffer and publish their own semantic
  events. The pipeline therefore does NOT re-run them; it *owns their lifecycle*
  as a group and provides an optional synchronous ``process_frame`` path
  (used for combined VisionResults / tests) that calls each detector's injected
  backend without coupling detectors to one another.
* **Add/remove without touching VisionManager.** Detectors can be added or
  removed on the pipeline at runtime. The whole pipeline registers with the
  VisionManager as a single Detector, so the manager is never edited to gain a
  new detector (Open/Closed).

It observes only - it never changes behaviour, emotion, mode, speech, or
hardware.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .performance_monitor import PerformanceMonitor
from .vision_result import VisionResult

log = get_logger("vision.pipeline")


@runtime_checkable
class PipelineDetector(Protocol):
    """What the pipeline needs from a detector: the Stage-1 Detector lifecycle,
    plus a name. (Detectors also run their own threads; the pipeline groups
    them.)"""
    name: str
    def initialize(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health_check(self) -> bool: ...


class VisionPipeline:
    """Groups detectors, manages their shared lifecycle, merges results, and
    reports pipeline events + performance. Registers with the VisionManager as a
    single Detector."""

    name = "pipeline"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 monitor: PerformanceMonitor | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._monitor = monitor or PerformanceMonitor(clock=clock)
        self._clock = clock

        self._lock = threading.RLock()
        self._detectors: dict[str, PipelineDetector] = {}
        self._enabled: dict[str, bool] = {}
        self._started = False

    # ----------------------------------------------- detector registration
    def add_detector(self, detector: PipelineDetector, enabled: bool = True) -> None:
        """Add a detector to the pipeline (optionally starting it if running).
        Does NOT require modifying the VisionManager."""
        with self._lock:
            if detector.name in self._detectors:
                raise ValueError(f"duplicate detector '{detector.name}'")
            self._detectors[detector.name] = detector
            self._enabled[detector.name] = enabled
            running = self._started
        if running and enabled:
            detector.initialize()
            detector.start()
        log.info("pipeline added detector '%s' (enabled=%s)",
                 detector.name, enabled)

    def remove_detector(self, name: str) -> bool:
        with self._lock:
            detector = self._detectors.pop(name, None)
            self._enabled.pop(name, None)
        if detector is None:
            return False
        try:
            detector.stop()
        except Exception:                               # noqa: BLE001
            log.exception("error stopping detector '%s'", name)
        log.info("pipeline removed detector '%s'", name)
        return True

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable/disable a detector at runtime; starts/stops it if the pipeline
        is running."""
        with self._lock:
            if name not in self._detectors:
                raise KeyError(name)
            was = self._enabled[name]
            self._enabled[name] = enabled
            detector = self._detectors[name]
            running = self._started
        if running and enabled and not was:
            detector.initialize(); detector.start()
        elif running and not enabled and was:
            detector.stop()
        log.info("pipeline detector '%s' enabled=%s", name, enabled)

    @property
    def detectors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._detectors))

    def enabled_detectors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(n for n, e in self._enabled.items() if e))

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        with self._lock:
            items = [(n, d) for n, d in self._detectors.items()
                     if self._enabled[n]]
        for name, d in items:
            try:
                d.initialize()
            except Exception as exc:                    # noqa: BLE001
                self._fail(f"detector '{name}' failed to initialize", exc)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            items = [(n, d) for n, d in self._detectors.items()
                     if self._enabled[n]]
        for name, d in items:
            try:
                d.start()
            except Exception as exc:                    # noqa: BLE001
                self._fail(f"detector '{name}' failed to start", exc)
        self._bus.emit(RobotEvent.PIPELINE_STARTED,
                       {"detectors": list(self.enabled_detectors())},
                       source=self.name)
        log.info("pipeline started")

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
            items = list(self._detectors.items())
        for name, d in reversed(items):
            try:
                d.stop()
            except Exception:                           # noqa: BLE001
                log.exception("error stopping detector '%s'", name)
        self._bus.emit(RobotEvent.PIPELINE_STOPPED, {}, source=self.name)
        log.info("pipeline stopped")

    def health_check(self) -> bool:
        with self._lock:
            if not self._started:
                return False
            items = [(n, d) for n, d in self._detectors.items()
                     if self._enabled[n]]
        for name, d in items:
            try:
                if not d.health_check():
                    return False
            except Exception:                           # noqa: BLE001
                return False
        return True

    # ------------------------------------------------- synchronous merge path
    def process_frame(self, frame: Frame,
                      infer: Callable[[str, Frame], VisionResult] | None = None
                      ) -> VisionResult:
        """Optionally run a synchronous merge pass: call ``infer(name, frame)``
        for each enabled detector, time it, and merge the results into one
        combined VisionResult. Used for combined snapshots/tests; the live
        detectors also run asynchronously on their own threads.

        If ``infer`` is None, returns an empty combined result (the async
        detectors are the source of truth in production)."""
        combined: list = []
        with self._lock:
            names = [n for n, e in self._enabled.items() if e]
        for name in names:
            if infer is None:
                continue
            t0 = self._clock()
            try:
                result = infer(name, frame)
            except Exception as exc:                    # noqa: BLE001
                self._fail(f"detector '{name}' inference error", exc)
                continue
            elapsed_ms = (self._clock() - t0) * 1000.0
            self._monitor.record_detector_time(name, elapsed_ms)
            if result is not None:
                combined.extend(result.detections)
        self._monitor.record_processed_frame()
        self._monitor.record_dropped(self._buffer.dropped_count)
        self._monitor.record_camera_fps(0.0)   # camera fps set elsewhere
        return VisionResult(detector=self.name, detections=tuple(combined),
                            frame_index=frame.index)

    # -------------------------------------------------------------- monitor
    @property
    def monitor(self) -> PerformanceMonitor:
        return self._monitor

    def performance(self) -> dict:
        self._monitor.record_dropped(self._buffer.dropped_count)
        return self._monitor.as_dict()

    # ------------------------------------------------------------- internal
    def _fail(self, message: str, exc: Exception) -> None:
        log.exception(message)
        self._bus.emit(RobotEvent.PIPELINE_ERROR,
                       {"message": message, "error": str(exc)},
                       source=self.name)
