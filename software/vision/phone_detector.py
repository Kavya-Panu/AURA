"""
vision/phone_detector.py
========================
Phone detection (Stage 4). Uses YOLOv8 on the real system.

COMPLETELY INDEPENDENT: it never imports MediaPipe, the face detector, or the
person detector. It defines its OWN object-detection backend Protocol in-file
(sharing no code with the person detector). Inference sits behind
:class:`PhoneDetectionBackend` (dependency injection):
* :class:`YOLOPhoneBackend` - real; lazily imports ``ultralytics`` (YOLOv8),
  filters the COCO 'cell phone' class. CPU / CUDA / future TensorRT.
* :class:`FakePhoneBackend` - scripted; for tests / no hardware.

Responsibilities (only): detect a cell phone, track how long it stays visible,
and publish ``PHONE_DETECTED``, ``PHONE_DURATION_UPDATED``, and ``PHONE_REMOVED``
(the last maps to the core ``PHONE_GONE`` event). It does NOT implement Focus
Mode and does NOT warn the user - the Behavior/Focus layers do that. It only
publishes events.
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

log = get_logger("vision.phone")


@dataclass(frozen=True)
class PhoneBox:
    """A detected phone in pixel coordinates."""
    x: int
    y: int
    width: int
    height: int
    confidence: float


@runtime_checkable
class PhoneDetectionBackend(Protocol):
    """Runs phone inference on one frame. Real impl wraps YOLOv8."""
    def load(self) -> None: ...
    def detect(self, frame: object, width: int, height: int) -> list[PhoneBox]: ...
    def close(self) -> None: ...


class FakePhoneBackend:
    """Scripted phone backend for tests (FIFO of box-lists)."""

    def __init__(self, script: list[list[PhoneBox]] | None = None) -> None:
        self._script = list(script or [])
        self._i = 0
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def queue(self, phones: list[PhoneBox]) -> None:
        self._script.append(phones)

    def detect(self, frame: object, width: int, height: int) -> list[PhoneBox]:
        if not self._script:
            return []
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        return list(self._script[idx])

    def close(self) -> None:
        self.loaded = False


class YOLOPhoneBackend:
    """Real YOLOv8 backend filtering the COCO 'cell phone' class (id 67).
    Lazily imports ultralytics."""

    _PHONE_CLASS_ID = 67

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
        log.info("YOLOv8 phone model '%s' on %s", self._model_path, device)

    def detect(self, frame: object, width: int, height: int) -> list[PhoneBox]:
        if self._model is None:
            raise DetectorError("YOLOPhoneBackend.detect before load()")
        results = self._model.predict(frame, device=self._device,
                                      classes=[self._PHONE_CLASS_ID],
                                      conf=self._min_conf, verbose=False)
        boxes: list[PhoneBox] = []
        for r in results:
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                boxes.append(PhoneBox(int(x1), int(y1), int(x2 - x1),
                                      int(y2 - y1), float(b.conf[0])))
        return boxes

    def close(self) -> None:
        self._model = None


class PhoneDetector:
    """Detects a phone and tracks visibility duration; publishes PHONE_DETECTED,
    PHONE_DURATION_UPDATED and PHONE_REMOVED. No Focus Mode, no warnings - only
    events. Independent of all other detectors."""

    name = "phone"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: PhoneDetectionBackend,
                 min_confidence: float = 0.4,
                 duration_update_interval_s: float = 1.0,
                 disappear_grace_s: float = 0.6,
                 clock=time.monotonic) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._min_conf = min_confidence
        self._update_interval = duration_update_interval_s
        self._grace = disappear_grace_s
        self._clock = clock

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        # Visibility state.
        self._visible = False
        self._present_since = 0.0
        self._last_seen = 0.0
        self._last_update_emit = 0.0

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        self._backend.load()
        log.info("phone detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-phone",
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
                self._maybe_expire()
                continue
            self._last_index = frame.index
            self._frame_counter += 1
            if self._frame_counter % every_n != 0:
                continue
            try:
                self._process(frame)
            except Exception:                           # noqa: BLE001
                log.exception("phone detection failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        boxes = [b for b in self._backend.detect(frame.data, frame.width,
                                                 frame.height)
                 if b.confidence >= self._min_conf]
        now = self._clock()
        if boxes:
            best = max(boxes, key=lambda b: b.confidence)
            if not self._visible:
                self._visible = True
                self._present_since = now
                self._last_update_emit = now
                self._bus.emit(
                    RobotEvent.PHONE_DETECTED,
                    {"confidence": round(best.confidence, 3),
                     "box": [best.x, best.y, best.width, best.height],
                     "frame_index": frame.index},
                    source=self.name)
            self._last_seen = now
            # Periodic duration updates while visible.
            if now - self._last_update_emit >= self._update_interval:
                self._last_update_emit = now
                self._bus.emit(
                    RobotEvent.PHONE_DURATION_UPDATED,
                    {"duration_s": round(now - self._present_since, 2),
                     "frame_index": frame.index},
                    source=self.name)
        else:
            self._maybe_expire()

    def _maybe_expire(self) -> None:
        """Emit PHONE_REMOVED once the phone has been gone past the grace time."""
        if not self._visible:
            return
        now = self._clock()
        if now - self._last_seen >= self._grace:
            duration = self._last_seen - self._present_since
            self._visible = False
            self._bus.emit(
                RobotEvent.PHONE_GONE,      # -> core PHONE_GONE
                {"total_duration_s": round(max(0.0, duration), 2)},
                source=self.name)

    # ------------------------------------------------------------- readonly
    @property
    def is_phone_visible(self) -> bool:
        return self._visible

    @property
    def visible_duration_s(self) -> float:
        if not self._visible:
            return 0.0
        return self._clock() - self._present_since
