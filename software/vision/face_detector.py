"""
vision/face_detector.py
=======================
Face detection (Stage 3). Uses MediaPipe Face Detection on the real system.

This module is COMPLETELY INDEPENDENT: it never imports YOLO, the person
detector, or the phone detector. Face inference sits behind a
:class:`FaceDetectionBackend` Protocol (dependency injection):
* :class:`MediaPipeFaceBackend` - real; lazily imports ``mediapipe`` (+ optional
  GPU). Importing this module never requires MediaPipe.
* :class:`FakeFaceBackend`      - scripted boxes; for tests / no hardware.

Responsibilities (only): detect one or more faces, return bounding boxes +
confidence, publish ``FACE_FOUND`` / ``FACE_LOST``. It does NOT track faces
(that is :mod:`vision.face_tracker`) and does not touch hardware.

It implements the existing Stage-1 ``Detector`` protocol
(initialize/start/stop/health_check) and reads frames from the Stage-2
``FrameBuffer`` on its own thread (asynchronous, frame-skipping, non-blocking).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .vision_config import VisionConfig
from .vision_exceptions import DetectorError
from .vision_result import (
    BoundingBox, Detection, DetectionKind, VisionResult,
)

log = get_logger("vision.face")


@dataclass(frozen=True)
class FaceBox:
    """A detected face in pixel coordinates."""
    x: int
    y: int
    width: int
    height: int
    confidence: float


@runtime_checkable
class FaceDetectionBackend(Protocol):
    """Runs face inference on one frame. Real impl wraps MediaPipe."""
    def load(self) -> None: ...
    def detect(self, frame: object, width: int, height: int) -> list[FaceBox]: ...
    def close(self) -> None: ...


class FakeFaceBackend:
    """Scripted face backend for tests: returns a queued list of FaceBox per
    call (FIFO), repeating the last script entry once exhausted."""

    def __init__(self, script: list[list[FaceBox]] | None = None) -> None:
        self._script = list(script or [])
        self._i = 0
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def queue(self, faces: list[FaceBox]) -> None:
        self._script.append(faces)

    def detect(self, frame: object, width: int, height: int) -> list[FaceBox]:
        if not self._script:
            return []
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        return list(self._script[idx])

    def close(self) -> None:
        self.loaded = False


class MediaPipeFaceBackend:
    """Real backend using MediaPipe Face Detection. Lazily imported."""

    def __init__(self, min_confidence: float = 0.5, model_selection: int = 0) -> None:
        self._min_conf = min_confidence
        self._model_selection = model_selection
        self._detector = None

    def load(self) -> None:
        try:
            import mediapipe as mp                      # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise DetectorError("MediaPipe not available",
                                {"error": str(exc)}) from exc
        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=self._model_selection,
            min_detection_confidence=self._min_conf)

    def detect(self, frame: object, width: int, height: int) -> list[FaceBox]:
        if self._detector is None:
            raise DetectorError("MediaPipeFaceBackend.detect before load()")
        results = self._detector.process(frame)         # frame = RGB ndarray
        faces: list[FaceBox] = []
        for det in (results.detections or []):
            box = det.location_data.relative_bounding_box
            x = int(box.xmin * width)
            y = int(box.ymin * height)
            w = int(box.width * width)
            h = int(box.height * height)
            conf = float(det.score[0]) if det.score else 0.0
            faces.append(FaceBox(x, y, w, h, conf))
        return faces

    def close(self) -> None:
        if self._detector is not None:
            try:
                self._detector.close()
            finally:
                self._detector = None


class FaceDetector:
    """Detects faces and publishes FACE_FOUND / FACE_LOST. Independent of all
    other detectors. Satisfies the Stage-1 Detector protocol."""

    name = "face"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: FaceDetectionBackend,
                 min_confidence: float = 0.5) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._min_conf = min_confidence

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        self._faces_present = False

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        self._backend.load()
        log.info("face detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-face",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._backend.close()

    def health_check(self) -> bool:
        return self._running.is_set() and (
            self._thread is not None and self._thread.is_alive())

    # --------------------------------------------------------------- worker
    def _loop(self) -> None:
        every_n = max(1, self._cfg.processing.detect_every_n_frames)
        while self._running.is_set():
            frame = self._buffer.wait_for_frame(since_index=self._last_index,
                                                timeout_s=0.5)
            if frame is None:
                continue
            self._last_index = frame.index
            self._frame_counter += 1
            if self._frame_counter % every_n != 0:      # frame skipping
                continue
            try:
                self._process(frame)
            except Exception:                           # noqa: BLE001
                log.exception("face detection failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        t0 = time.perf_counter()
        boxes = [b for b in self._backend.detect(frame.data, frame.width,
                                                 frame.height)
                 if b.confidence >= self._min_conf]
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        detections = tuple(
            Detection(kind=DetectionKind.FACE, confidence=b.confidence,
                      box=BoundingBox(b.x, b.y, b.width, b.height), label="face")
            for b in boxes)
        result = VisionResult(detector=self.name, detections=detections,
                              frame_index=frame.index, processing_ms=elapsed_ms)

        # Transition logic -> semantic events.
        if boxes:
            self._bus.emit(
                RobotEvent.FACE_FOUND,
                {"count": len(boxes),
                 "faces": [{"box": [b.x, b.y, b.width, b.height],
                            "confidence": round(b.confidence, 3)} for b in boxes],
                 "frame": {"width": frame.width, "height": frame.height},
                 "frame_index": frame.index},
                source=self.name)
            self._faces_present = True
        elif self._faces_present:
            self._bus.emit(RobotEvent.FACE_LOST,
                           {"frame_index": frame.index}, source=self.name)
            self._faces_present = False
