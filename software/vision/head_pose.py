"""
vision/head_pose.py
===================
Head-pose estimation (final Vision stage). Uses MediaPipe FaceMesh landmarks.

COMPLETELY INDEPENDENT: never imports YOLO or another detector; owns its own
FaceMesh backend instance. Estimates yaw/pitch as normalized orientation
(-1..+1) from landmark geometry, classifies into Left/Right/Up/Down/Centered,
and publishes ``HEAD_LEFT`` / ``HEAD_RIGHT`` / ``HEAD_UP`` / ``HEAD_DOWN`` /
``HEAD_CENTER`` on transitions. It does NOT control servos - it only reports.
Implements the Stage-1 Detector protocol; reads frames from the FrameBuffer.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .vision_config import VisionConfig
from .vision_exceptions import DetectorError

log = get_logger("vision.head_pose")

# FaceMesh indices: nose tip 1; left/right face edges 234/454; forehead 10; chin 152.
_NOSE = 1
_FACE_LEFT = 234
_FACE_RIGHT = 454
_FOREHEAD = 10
_CHIN = 152


class HeadDirection(Enum):
    CENTER = "HEAD_CENTER"
    LEFT = "HEAD_LEFT"
    RIGHT = "HEAD_RIGHT"
    UP = "HEAD_UP"
    DOWN = "HEAD_DOWN"


@dataclass(frozen=True)
class FaceMesh:
    """Normalized (x, y) FaceMesh landmarks for a single face."""
    points: tuple[tuple[float, float], ...]

    def x(self, i: int) -> float:
        return self.points[i][0]

    def y(self, i: int) -> float:
        return self.points[i][1]


@dataclass(frozen=True)
class HeadOrientation:
    """Normalized head orientation: yaw/pitch in -1..+1 and a classification."""
    yaw: float               # -1 (left) .. +1 (right)
    pitch: float             # -1 (up)   .. +1 (down)
    direction: HeadDirection


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


class MediaPipeFaceMeshBackend:
    """Real backend using MediaPipe FaceMesh. Lazily imported."""

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
            max_num_faces=1, refine_landmarks=True,
            min_detection_confidence=self._min_conf,
            min_tracking_confidence=self._min_conf)

    def detect(self, frame: object, width: int, height: int) -> list[FaceMesh]:
        if self._mesh is None:
            raise DetectorError("MediaPipeFaceMeshBackend.detect before load()")
        results = self._mesh.process(frame)
        return [FaceMesh(tuple((p.x, p.y) for p in lm.landmark))
                for lm in (results.multi_face_landmarks or [])]

    def close(self) -> None:
        if self._mesh is not None:
            try:
                self._mesh.close()
            finally:
                self._mesh = None


def estimate_orientation(face: FaceMesh, center_zone: float = 0.25) -> HeadOrientation:
    """Estimate yaw/pitch from nose position relative to the face box, and
    classify into a direction. Pure function (testable)."""
    left_x, right_x = face.x(_FACE_LEFT), face.x(_FACE_RIGHT)
    top_y, bottom_y = face.y(_FOREHEAD), face.y(_CHIN)
    width = (right_x - left_x) or 1e-6
    height = (bottom_y - top_y) or 1e-6

    # Nose horizontal position within face -> yaw. 0.5 = centered.
    nose_fx = (face.x(_NOSE) - left_x) / width
    nose_fy = (face.y(_NOSE) - top_y) / height
    yaw = max(-1.0, min(1.0, (nose_fx - 0.5) * 2.0))
    pitch = max(-1.0, min(1.0, (nose_fy - 0.5) * 2.0))

    direction = HeadDirection.CENTER
    if abs(yaw) >= abs(pitch):
        if yaw < -center_zone:
            direction = HeadDirection.LEFT
        elif yaw > center_zone:
            direction = HeadDirection.RIGHT
    if direction is HeadDirection.CENTER:
        if pitch < -center_zone:
            direction = HeadDirection.UP
        elif pitch > center_zone:
            direction = HeadDirection.DOWN
    return HeadOrientation(round(yaw, 4), round(pitch, 4), direction)


class HeadPoseDetector:
    """Estimates head orientation and publishes HEAD_* events on direction
    changes. Never controls servos."""

    name = "head_pose"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: FaceMeshBackend,
                 center_zone: float = 0.25) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._center_zone = center_zone

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        self._direction: HeadDirection | None = None

    def initialize(self) -> None:
        self._backend.load()
        log.info("head pose detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-head",
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
                log.exception("head pose failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        faces = self._backend.detect(frame.data, frame.width, frame.height)
        if not faces:
            return
        orient = estimate_orientation(faces[0], self._center_zone)
        if orient.direction != self._direction:
            self._direction = orient.direction
            self._bus.emit(RobotEvent[orient.direction.value],
                           {"yaw": orient.yaw, "pitch": orient.pitch,
                            "frame_index": frame.index}, source=self.name)

    @property
    def direction(self) -> HeadDirection | None:
        return self._direction
