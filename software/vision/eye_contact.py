"""
vision/eye_contact.py
=====================
Eye-contact / gaze estimation (final Vision stage). Uses MediaPipe FaceMesh
(with iris refinement) on the real system.

COMPLETELY INDEPENDENT: never imports YOLO or another detector; owns its own
FaceMesh backend instance. Estimates whether the user is looking at AURA from
iris position within the eye, tracks eye-contact duration, and publishes
``LOOKING_AT_ROBOT`` / ``LOOKING_AWAY`` on transitions (with duration in the
payload). It never speaks or acts - it only reports. Implements the Stage-1
Detector protocol; reads frames from the Stage-2 FrameBuffer.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .vision_config import VisionConfig
from .vision_exceptions import DetectorError

log = get_logger("vision.eye_contact")

# FaceMesh (refined) indices: left eye corners 33/133, left iris center 468;
# right eye corners 362/263, right iris center 473.
_L_EYE_OUT, _L_EYE_IN, _L_IRIS = 33, 133, 468
_R_EYE_IN, _R_EYE_OUT, _R_IRIS = 362, 263, 473


@dataclass(frozen=True)
class FaceMesh:
    """Normalized (x, y) FaceMesh landmarks (with iris) for a single face."""
    points: tuple[tuple[float, float], ...]

    def x(self, i: int) -> float:
        return self.points[i][0]

    def has(self, i: int) -> bool:
        return i < len(self.points)


@runtime_checkable
class FaceMeshBackend(Protocol):
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


class MediaPipeIrisBackend:
    """Real backend using MediaPipe FaceMesh with iris refinement. Lazily
    imported."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        self._min_conf = min_confidence
        self._mesh = None

    def load(self) -> None:
        try:
            import mediapipe as mp                      # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise DetectorError("MediaPipe not available",
                                {"error": str(exc)}) from exc
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1, refine_landmarks=True,      # enables iris landmarks
            min_detection_confidence=self._min_conf,
            min_tracking_confidence=self._min_conf)

    def detect(self, frame: object, width: int, height: int) -> list[FaceMesh]:
        if self._mesh is None:
            raise DetectorError("MediaPipeIrisBackend.detect before load()")
        results = self._mesh.process(frame)
        return [FaceMesh(tuple((p.x, p.y) for p in lm.landmark))
                for lm in (results.multi_face_landmarks or [])]

    def close(self) -> None:
        if self._mesh is not None:
            try:
                self._mesh.close()
            finally:
                self._mesh = None


def gaze_centered(face: FaceMesh, tolerance: float = 0.22) -> bool:
    """True if both irises sit near the horizontal center of their eyes, which
    approximates looking at the camera. Pure function (testable)."""
    if not (face.has(_L_IRIS) and face.has(_R_IRIS)):
        return False

    def ratio(out_i: int, in_i: int, iris_i: int) -> float:
        out_x, in_x, iris_x = face.x(out_i), face.x(in_i), face.x(iris_i)
        span = (in_x - out_x) or 1e-6
        return (iris_x - out_x) / span            # 0.5 = centered

    left = ratio(_L_EYE_OUT, _L_EYE_IN, _L_IRIS)
    right = ratio(_R_EYE_OUT, _R_EYE_IN, _R_IRIS)
    return (abs(left - 0.5) < tolerance) and (abs(right - 0.5) < tolerance)


class EyeContactDetector:
    """Estimates eye contact + duration; publishes LOOKING_AT_ROBOT /
    LOOKING_AWAY on transitions."""

    name = "eye_contact"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: FaceMeshBackend,
                 tolerance: float = 0.22,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._tolerance = tolerance
        self._clock = clock

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        self._looking: bool | None = None
        self._since = 0.0

    def initialize(self) -> None:
        self._backend.load()
        log.info("eye contact detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-eye",
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
                log.exception("eye contact failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        faces = self._backend.detect(frame.data, frame.width, frame.height)
        if not faces:
            return
        looking = gaze_centered(faces[0], self._tolerance)
        now = self._clock()
        if looking != self._looking:
            # Duration of the state we are LEAVING (for LOOKING_AWAY payload).
            prev_duration = now - self._since if self._looking is not None else 0.0
            self._looking = looking
            self._since = now
            event = (RobotEvent.LOOKING_AT_ROBOT if looking
                     else RobotEvent.LOOKING_AWAY)
            self._bus.emit(event,
                           {"duration_s": round(prev_duration, 2),
                            "frame_index": frame.index}, source=self.name)

    @property
    def is_looking(self) -> bool | None:
        return self._looking

    @property
    def contact_duration_s(self) -> float:
        if not self._looking:
            return 0.0
        return self._clock() - self._since
