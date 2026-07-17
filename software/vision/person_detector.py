"""
vision/person_detector.py
=========================
Person detection (Stage 4). Uses YOLOv8 on the real system.

COMPLETELY INDEPENDENT: it never imports MediaPipe, the face detector, or the
phone detector. It defines its OWN object-detection backend Protocol in-file so
it shares no code with the phone detector. Inference sits behind
:class:`PersonDetectionBackend` (dependency injection):
* :class:`YOLOPersonBackend` - real; lazily imports ``ultralytics`` (YOLOv8),
  supports CPU / CUDA (and future TensorRT via the exported engine path).
* :class:`FakePersonBackend` - scripted boxes; for tests / no hardware.

Responsibilities (only): detect persons (bounding box, confidence, tracking id),
publish ``PERSON_FOUND`` / ``PERSON_LEFT``. It implements the Stage-1 Detector
protocol and reads frames from the Stage-2 FrameBuffer on its own thread.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .vision_config import VisionConfig
from .vision_exceptions import DetectorError
from .vision_result import BoundingBox, Detection, DetectionKind, VisionResult

log = get_logger("vision.person")


@dataclass(frozen=True)
class PersonBox:
    """A detected person in pixel coordinates."""
    x: int
    y: int
    width: int
    height: int
    confidence: float


@runtime_checkable
class PersonDetectionBackend(Protocol):
    """Runs person inference on one frame. Real impl wraps YOLOv8."""
    def load(self) -> None: ...
    def detect(self, frame: object, width: int, height: int) -> list[PersonBox]: ...
    def close(self) -> None: ...


class FakePersonBackend:
    """Scripted person backend for tests (FIFO of box-lists)."""

    def __init__(self, script: list[list[PersonBox]] | None = None) -> None:
        self._script = list(script or [])
        self._i = 0
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def queue(self, persons: list[PersonBox]) -> None:
        self._script.append(persons)

    def detect(self, frame: object, width: int, height: int) -> list[PersonBox]:
        if not self._script:
            return []
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        return list(self._script[idx])

    def close(self) -> None:
        self.loaded = False


class YOLOPersonBackend:
    """Real YOLOv8 backend filtering the COCO 'person' class (id 0). Lazily
    imports ultralytics so importing this module never requires it."""

    _PERSON_CLASS_ID = 0

    def __init__(self, model_path: str = "yolov8n.pt", device: str = "auto",
                 min_confidence: float = 0.4) -> None:
        self._model_path = model_path
        self._device = device
        self._min_conf = min_confidence
        self._model = None

    def load(self) -> None:
        try:
            from ultralytics import YOLO                # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise DetectorError("ultralytics (YOLOv8) not available",
                                {"error": str(exc)}) from exc
        device = self._device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:                           # noqa: BLE001
                device = "cpu"
        self._model = YOLO(self._model_path)
        self._device = device
        log.info("YOLOv8 person model '%s' on %s", self._model_path, device)

    def detect(self, frame: object, width: int, height: int) -> list[PersonBox]:
        if self._model is None:
            raise DetectorError("YOLOPersonBackend.detect before load()")
        results = self._model.predict(frame, device=self._device,
                                      classes=[self._PERSON_CLASS_ID],
                                      conf=self._min_conf, verbose=False)
        boxes: list[PersonBox] = []
        for r in results:
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                boxes.append(PersonBox(int(x1), int(y1), int(x2 - x1),
                                       int(y2 - y1), float(b.conf[0])))
        return boxes

    def close(self) -> None:
        self._model = None


@dataclass
class _PersonTrack:
    track_id: int
    box: PersonBox
    misses: int = 0
    last_seen: float = field(default_factory=time.monotonic)


class PersonDetector:
    """Detects persons with simple tracking IDs; publishes PERSON_FOUND /
    PERSON_LEFT. Independent of all other detectors."""

    name = "person"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: PersonDetectionBackend,
                 min_confidence: float = 0.4, match_distance: float = 0.25,
                 max_misses: int = 5) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._min_conf = min_confidence
        self._match_distance = match_distance
        self._max_misses = max_misses

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        self._tracks: dict[int, _PersonTrack] = {}
        self._next_id = 1
        self._present = False

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        self._backend.load()
        log.info("person detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-person",
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
            if self._frame_counter % every_n != 0:
                continue
            try:
                self._process(frame)
            except Exception:                           # noqa: BLE001
                log.exception("person detection failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        t0 = time.perf_counter()
        boxes = [b for b in self._backend.detect(frame.data, frame.width,
                                                 frame.height)
                 if b.confidence >= self._min_conf]
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        fw = max(1, frame.width or 1)
        fh = max(1, frame.height or 1)

        self._assign_ids(boxes, fw, fh)
        active = [t for t in self._tracks.values() if t.misses == 0]

        if active:
            self._bus.emit(
                RobotEvent.PERSON_FOUND,
                {"count": len(active),
                 "persons": [{"id": t.track_id,
                              "box": [t.box.x, t.box.y, t.box.width, t.box.height],
                              "confidence": round(t.box.confidence, 3)}
                             for t in active],
                 "frame_index": frame.index},
                source=self.name)
            self._present = True
        elif self._present:
            self._bus.emit(RobotEvent.PERSON_LEFT,
                           {"frame_index": frame.index}, source=self.name)
            self._present = False

        _ = VisionResult(self.name, frame_index=frame.index,
                         processing_ms=elapsed_ms)   # available for future sinks

    def _assign_ids(self, boxes: list[PersonBox], fw: int, fh: int) -> None:
        def center(b: PersonBox) -> tuple[float, float]:
            return ((b.x + b.width / 2) / fw, (b.y + b.height / 2) / fh)
        unmatched = set(self._tracks)
        for b in boxes:
            bx, by = center(b)
            best_id, best_d = None, self._match_distance
            for tid in unmatched:
                tb = self._tracks[tid].box
                tx, ty = center(tb)
                d = ((tx - bx) ** 2 + (ty - by) ** 2) ** 0.5
                if d < best_d:
                    best_id, best_d = tid, d
            if best_id is not None:
                self._tracks[best_id].box = b
                self._tracks[best_id].misses = 0
                self._tracks[best_id].last_seen = time.monotonic()
                unmatched.discard(best_id)
            else:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = _PersonTrack(tid, b)
        for tid in list(unmatched):
            self._tracks[tid].misses += 1
            if self._tracks[tid].misses > self._max_misses:
                del self._tracks[tid]

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tracks.values() if t.misses == 0)
