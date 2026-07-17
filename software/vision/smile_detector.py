"""
vision/smile_detector.py
========================
Smile estimation (final Vision stage). Uses MediaPipe FaceMesh landmarks on the
real system.

COMPLETELY INDEPENDENT: never imports YOLO or another detector. Inference sits
behind a :class:`FaceMeshBackend` Protocol (dependency injection):
* :class:`MediaPipeFaceMeshBackend` - real; lazily imports ``mediapipe`` and
  returns normalized face landmarks.
* :class:`FakeFaceMeshBackend`      - scripted landmarks; for tests.

Estimates smiling / not-smiling with a confidence from a simple geometric mouth
ratio, and publishes ``USER_SMILING`` / ``USER_NOT_SMILING`` on transitions. It
never changes emotions or behaviour - it only reports. Implements the Stage-1
Detector protocol and reads frames from the Stage-2 FrameBuffer on its thread.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .vision_config import VisionConfig
from .vision_exceptions import DetectorError

log = get_logger("vision.smile")

# FaceMesh landmark indices used here (mouth corners + lips + eye spacing).
_MOUTH_LEFT = 61
_MOUTH_RIGHT = 291
_LIP_TOP = 13
_LIP_BOTTOM = 14
_EYE_LEFT = 33
_EYE_RIGHT = 263


@dataclass(frozen=True)
class FaceMesh:
    """Normalized (x, y) FaceMesh landmarks for a single face."""
    points: tuple[tuple[float, float], ...]

    def x(self, i: int) -> float:
        return self.points[i][0]

    def y(self, i: int) -> float:
        return self.points[i][1]


@runtime_checkable
class FaceMeshBackend(Protocol):
    """Returns FaceMesh landmarks for a frame. Real impl wraps MediaPipe."""
    def load(self) -> None: ...
    def detect(self, frame: object, width: int, height: int) -> list[FaceMesh]: ...
    def close(self) -> None: ...


class FakeFaceMeshBackend:
    """Scripted FaceMesh backend for tests (FIFO of landmark-lists)."""

    def __init__(self, script: list[list[FaceMesh]] | None = None) -> None:
        self._script = list(script or [])
        self._i = 0
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def queue(self, faces: list[FaceMesh]) -> None:
        self._script.append(faces)

    def detect(self, frame: object, width: int, height: int) -> list[FaceMesh]:
        if not self._script:
            return []
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        return list(self._script[idx])

    def close(self) -> None:
        self.loaded = False


class MediaPipeFaceMeshBackend:
    """Real backend using MediaPipe FaceMesh. Lazily imported. Shared shape with
    the eye-contact and head-pose detectors, but each detector owns its own
    instance (no cross-detector coupling)."""

    def __init__(self, max_faces: int = 1, min_confidence: float = 0.5) -> None:
        self._max_faces = max_faces
        self._min_conf = min_confidence
        self._mesh = None

    def load(self) -> None:
        try:
            import mediapipe as mp                      # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise DetectorError("MediaPipe not available",
                                {"error": str(exc)}) from exc
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=self._max_faces, refine_landmarks=True,
            min_detection_confidence=self._min_conf,
            min_tracking_confidence=self._min_conf)

    def detect(self, frame: object, width: int, height: int) -> list[FaceMesh]:
        if self._mesh is None:
            raise DetectorError("MediaPipeFaceMeshBackend.detect before load()")
        results = self._mesh.process(frame)
        faces: list[FaceMesh] = []
        for lm in (results.multi_face_landmarks or []):
            faces.append(FaceMesh(tuple((p.x, p.y) for p in lm.landmark)))
        return faces

    def close(self) -> None:
        if self._mesh is not None:
            try:
                self._mesh.close()
            finally:
                self._mesh = None


def smile_ratio(face: FaceMesh) -> float:
    """Mouth-width / mouth-open ratio normalised by eye distance. Wide + closed
    lips => higher ratio => smiling. Returns a 0..1-ish confidence."""
    eye_dist = abs(face.x(_EYE_RIGHT) - face.x(_EYE_LEFT)) or 1e-6
    mouth_w = abs(face.x(_MOUTH_RIGHT) - face.x(_MOUTH_LEFT))
    mouth_open = abs(face.y(_LIP_BOTTOM) - face.y(_LIP_TOP))
    width_ratio = mouth_w / eye_dist            # ~0.9 neutral, >1.05 smiling
    open_penalty = min(1.0, mouth_open / eye_dist * 3.0)
    score = (width_ratio - 0.95) / 0.35 - 0.3 * open_penalty
    return max(0.0, min(1.0, score))


class SmileDetector:
    """Estimates smiling and publishes USER_SMILING / USER_NOT_SMILING."""

    name = "smile"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: FaceMeshBackend,
                 smile_threshold: float = 0.5) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._threshold = smile_threshold

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        self._smiling: bool | None = None

    def initialize(self) -> None:
        self._backend.load()
        log.info("smile detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-smile",
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
                log.exception("smile detection failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        faces = self._backend.detect(frame.data, frame.width, frame.height)
        if not faces:
            return
        conf = smile_ratio(faces[0])
        smiling = conf >= self._threshold
        if smiling != self._smiling:
            self._smiling = smiling
            event = RobotEvent.USER_SMILING if smiling else RobotEvent.USER_NOT_SMILING
            self._bus.emit(event, {"confidence": round(conf, 3),
                                   "frame_index": frame.index}, source=self.name)

    @property
    def is_smiling(self) -> bool | None:
        return self._smiling
