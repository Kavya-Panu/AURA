"""Laptop-webcam face following for AURA's animated pupils.

The detector runs independently from voice and sends a smoothed normalized
``GAZE x y`` target. It intentionally tracks only the largest visible face so
the robot does not jump between people.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from core.logger import get_logger
from .face_recognizer import FaceRecognition, SFaceRecognizer

log = get_logger("vision.face_follower")

GazeCallback = Callable[[float, float], None]
HeadCallback = Callable[[float], None]
StatusCallback = Callable[[str], None]
PauseCallback = Callable[[], bool]


@dataclass(frozen=True)
class FacePosition:
    x: float
    y: float
    confidence: float = 1.0


class FacePositionBackend(Protocol):
    def open(self) -> None: ...
    def read(self) -> FacePosition | None: ...
    def close(self) -> None: ...
    def is_open(self) -> bool: ...


class OpenCVHaarFaceBackend:
    """CPU face detector using YuNet, with Haar as an automatic fallback."""

    def __init__(self, camera_index: int = 0, width: int = 640,
                 height: int = 480, show_preview: bool = True,
                 recognizer: SFaceRecognizer | None = None) -> None:
        self._camera_index = int(camera_index)
        self._width = int(width)
        self._height = int(height)
        self._show_preview = bool(show_preview)
        self._window_name = "AURA Camera - face tracking (Q closes preview)"
        self._cv2 = None
        self._capture = None
        self._cascade = None
        self._yunet = None
        self._recognizer = recognizer
        self._frame_lock = threading.RLock()
        self._latest_frame = None
        self.detector_name = "Haar fallback"

    def open(self) -> None:
        import cv2

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            raise RuntimeError(f"Could not load face detector: {cascade_path}")

        capture = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self._camera_index)
        if not capture.isOpened():
            raise RuntimeError(f"Could not open camera {self._camera_index}")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        model_path = (
            Path(__file__).resolve().parents[1]
            / "models"
            / "face_detection_yunet_2023mar.onnx"
        )
        yunet = None
        if model_path.is_file() and hasattr(cv2, "FaceDetectorYN_create"):
            try:
                yunet = cv2.FaceDetectorYN_create(
                    str(model_path),
                    "",
                    (self._width, self._height),
                    0.58,
                    0.30,
                    5000,
                )
                self.detector_name = "OpenCV YuNet"
            except Exception:  # noqa: BLE001
                log.exception("YuNet initialization failed; using Haar fallback")

        self._cv2 = cv2
        self._capture = capture
        self._cascade = cascade
        self._yunet = yunet
        if self._recognizer is not None:
            if yunet is None:
                raise RuntimeError("Face recognition requires the YuNet detector model")
            self._recognizer.initialize(cv2)

    def read(self) -> FacePosition | None:
        if self._capture is None or self._cascade is None or self._cv2 is None:
            return None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            return None
        # VideoCapture returns a new array for each read. Keep the newest one
        # so on-demand object understanding can share this camera safely.
        with self._frame_lock:
            self._latest_frame = frame
        height, width = frame.shape[:2]
        selected = None
        selected_face_row = None
        confidence = 1.0
        if self._yunet is not None:
            self._yunet.setInputSize((width, height))
            _retval, detections = self._yunet.detect(frame)
            if detections is not None and len(detections) > 0:
                face = max(
                    detections,
                    key=lambda row: float(row[2]) * float(row[3]),
                )
                selected = tuple(float(value) for value in face[:4])
                selected_face_row = face.copy()
                confidence = float(face[-1])
        else:
            gray = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
            gray = self._cv2.equalizeHist(gray)
            faces = self._cascade.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(45, 45),
            )
            if len(faces) > 0:
                selected = max(
                    faces,
                    key=lambda box: int(box[2]) * int(box[3]),
                )

        recognition = FaceRecognition()
        if selected_face_row is not None and self._recognizer is not None:
            recognition = self._recognizer.observe(frame, selected_face_row)
        elif self._recognizer is not None:
            self._recognizer.face_lost()

        if self._show_preview:
            preview = frame.copy()
            self._cv2.line(
                preview, (width // 2, 0), (width // 2, height), (90, 90, 90), 1
            )
            if selected is not None:
                px, py, pw, ph = (int(value) for value in selected)
                colour = (0, 255, 120) if recognition.known else (0, 180, 255)
                self._cv2.rectangle(
                    preview, (px, py), (px + pw, py + ph), colour, 2
                )
                identity = recognition.name
                if recognition.enrolling:
                    identity = (
                        f"Learning {recognition.name} "
                        f"{recognition.enrollment_progress}/{recognition.enrollment_total}"
                    )
                elif self._recognizer is None:
                    identity = "Tracking"
                elif recognition.known:
                    identity = f"{recognition.name} {recognition.score:.0%}"
                self._cv2.putText(
                    preview, f"AURA: {identity}",
                    (px, max(24, py - 10)),
                    self._cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, colour, 2,
                )
            else:
                self._cv2.putText(
                    preview, "No face detected",
                    (20, 35), self._cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 180, 255), 2,
                )
            self._cv2.imshow(self._window_name, preview)
            key = self._cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                self._show_preview = False
                self._cv2.destroyWindow(self._window_name)

        if selected is None:
            return None

        x, y, w, h = selected
        center_x = float(x) + float(w) * 0.5
        # Track near the eyes instead of the bottom of the face box.
        center_y = float(y) + float(h) * 0.42
        nx = max(-1.0, min(1.0, center_x / max(1, width) * 2.0 - 1.0))
        ny = max(-1.0, min(1.0, center_y / max(1, height) * 2.0 - 1.0))
        return FacePosition(nx, ny, confidence)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._yunet = None
        with self._frame_lock:
            self._latest_frame = None
        if self._cv2 is not None:
            try:
                self._cv2.destroyWindow(self._window_name)
            except Exception:  # noqa: BLE001
                pass

    def is_open(self) -> bool:
        return self._capture is not None and bool(self._capture.isOpened())

    def snapshot(self):
        """Return an isolated copy of the newest camera frame."""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def begin_enrollment(self, name: str) -> bool:
        return bool(self._recognizer and self._recognizer.begin_enrollment(name))

    def known_people(self) -> tuple[str, ...]:
        return self._recognizer.names() if self._recognizer else ()

    def forget_person(self, name: str) -> bool:
        return bool(self._recognizer and self._recognizer.forget(name))

    @property
    def recognition_ready(self) -> bool:
        return bool(self._recognizer and self._recognizer.ready)


class FaceFollower:
    """Smooth face positions and rate-limit gaze commands to the ESP32."""

    name = "face_follower"

    def __init__(
        self,
        backend: FacePositionBackend,
        send_gaze: GazeCallback,
        send_head: HeadCallback | None = None,
        status: StatusCallback | None = None,
        *,
        pause_when: PauseCallback | None = None,
        update_hz: float = 8.0,
        smoothing: float = 0.14,
        mirror_x: bool = False,
        lost_timeout_s: float = 1.8,
        head_return_timeout_s: float = 6.0,
        head_center_deg: float = 95.0,
        head_range_deg: float = 42.0,
        head_reverse: bool = False,
    ) -> None:
        self._backend = backend
        self._send_gaze = send_gaze
        self._send_head = send_head
        self._status = status or (lambda _message: None)
        self._pause_when = pause_when or (lambda: False)
        self._interval = 1.0 / max(1.0, float(update_hz))
        self._alpha = max(0.05, min(1.0, float(smoothing)))
        self._mirror_x = bool(mirror_x)
        self._lost_timeout = max(0.2, float(lost_timeout_s))
        self._head_return_timeout = max(
            self._lost_timeout,
            float(head_return_timeout_s),
        )
        self._head_center = max(5.0, min(175.0, float(head_center_deg)))
        self._head_range = max(5.0, min(80.0, float(head_range_deg)))
        self._head_direction = -1.0 if head_reverse else 1.0
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = False
        self._x = 0.0
        self._y = 0.0
        self._last_sent = (99.0, 99.0)
        self._last_head_sent = 999.0
        self._last_seen = 0.0
        self._centered_after_loss = False
        self._head_centered_after_loss = False
        self._was_paused = False

    def initialize(self) -> None:
        try:
            self._backend.open()
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._status(f"Face tracking unavailable: {exc}")
            return
        self._available = True
        detector = getattr(self._backend, "detector_name", "face detector")
        self._status(
            f"Camera ready with {detector}; face tracking controls eyes and head."
        )

    def start(self) -> None:
        if not self._available or self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._loop,
            name="aura-face-following",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._backend.close()

    def health_check(self) -> bool:
        return self._available and self._backend.is_open()

    def enroll(self, name: str) -> bool:
        method = getattr(self._backend, "begin_enrollment", None)
        return bool(method and method(name))

    def known_people(self) -> tuple[str, ...]:
        method = getattr(self._backend, "known_people", None)
        return tuple(method()) if method else ()

    def forget_person(self, name: str) -> bool:
        method = getattr(self._backend, "forget_person", None)
        return bool(method and method(name))

    @property
    def recognition_ready(self) -> bool:
        return bool(getattr(self._backend, "recognition_ready", False))

    @property
    def face_visible(self) -> bool:
        """Whether a face was seen recently enough to count as present."""
        last_seen = self._last_seen
        return bool(
            self._available
            and last_seen > 0.0
            and time.monotonic() - last_seen <= self._lost_timeout
        )

    def snapshot(self):
        method = getattr(self._backend, "snapshot", None)
        return method() if method else None

    def _loop(self) -> None:
        while self._running.is_set():
            started = time.monotonic()
            try:
                position = self._backend.read()
                if self._pause_when():
                    self._was_paused = True
                else:
                    if self._was_paused:
                        # Force one fresh gaze command after the audio session.
                        self._last_sent = (99.0, 99.0)
                        self._was_paused = False
                    self._process(position, started)
            except Exception:  # noqa: BLE001
                log.exception("face tracking frame failed")
            remaining = self._interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)

    def _process(self, position: FacePosition | None, now: float) -> None:
        if position is None:
            if (self._last_seen > 0.0
                    and now - self._last_seen >= self._lost_timeout
                    and not self._centered_after_loss):
                self._x = self._y = 0.0
                self._send_if_changed(0.0, 0.0, force=True)
                self._centered_after_loss = True
            if (self._last_seen > 0.0
                    and now - self._last_seen >= self._head_return_timeout
                    and not self._head_centered_after_loss):
                self._send_head_if_changed(self._head_center, force=True)
                self._head_centered_after_loss = True
            return

        target_x = -position.x if self._mirror_x else position.x
        # A little gain lets the pupils use their available travel range.
        target_x = max(-1.0, min(1.0, target_x * 1.15))
        target_y = max(-1.0, min(1.0, position.y * 1.10))
        self._x = (1.0 - self._alpha) * self._x + self._alpha * target_x
        self._y = (1.0 - self._alpha) * self._y + self._alpha * target_y
        if abs(self._x) < 0.10:
            self._x = 0.0
        if abs(self._y) < 0.05:
            self._y = 0.0
        self._last_seen = now
        self._centered_after_loss = False
        self._head_centered_after_loss = False
        self._send_if_changed(self._x, self._y)
        head_angle = (
            self._head_center
            + self._head_direction * self._x * self._head_range
        )
        self._send_head_if_changed(head_angle)

    def _send_if_changed(self, x: float, y: float, force: bool = False) -> None:
        lx, ly = self._last_sent
        if not force and abs(x - lx) < 0.035 and abs(y - ly) < 0.035:
            return
        self._send_gaze(round(x, 3), round(y, 3))
        self._last_sent = (x, y)

    def _send_head_if_changed(self, angle: float, force: bool = False) -> None:
        if self._send_head is None:
            return
        angle = max(5.0, min(175.0, float(angle)))
        if not force and abs(angle - self._last_head_sent) < 2.0:
            return
        self._send_head(round(angle, 1))
        self._last_head_sent = angle
