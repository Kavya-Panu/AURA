"""
vision/camera_manager.py
========================
Owns the physical camera: opening/closing a capture stream, running capture on a
dedicated thread, pushing frames into the :class:`FrameBuffer`, auto-reconnecting
on disconnect, and reporting camera lifecycle through the existing Stage-1
:class:`VisionManager` seams (which publish on the Event Bus and update the
VisionContext).

Camera access is behind a :class:`CaptureBackend` Protocol (dependency
injection), so this module never imports OpenCV directly:
* :class:`OpenCVCaptureBackend` - real; lazily imports ``cv2``. Supports laptop
  webcams and USB cameras; a GStreamer pipeline string enables Jetson CSI
  cameras (future) with no code change here.
* :class:`FakeCaptureBackend`   - scripted frames + fault injection; for tests.

This module contains NO detection of any kind - only capture and delivery.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Protocol, runtime_checkable

from core.logger import get_logger

from .camera_selector import CameraInfo, CameraSelector
from .frame_buffer import Frame, FrameBuffer
from .vision_config import CameraConfig
from .vision_exceptions import CameraError

log = get_logger("vision.camera")


# ===========================================================================
#  Capture backend (dependency-injected camera access)
# ===========================================================================
@runtime_checkable
class CaptureBackend(Protocol):
    """Opens a stream and yields raw frames. Real impl wraps OpenCV."""
    def open(self, camera_id: int, config: CameraConfig) -> None: ...
    def read(self) -> tuple[bool, object, int, int]: ...   # ok, data, w, h
    def close(self) -> None: ...
    def is_open(self) -> bool: ...


class FakeCaptureBackend:
    """Scripted capture for tests: yields opaque frame payloads, and can be told
    to 'fail' after N reads to simulate a disconnect."""

    def __init__(self, frames: list[object] | None = None,
                 width: int = 640, height: int = 480,
                 fail_after: int | None = None,
                 loop: bool = True) -> None:
        self._frames = list(frames) if frames else [f"frame{i}" for i in range(1000)]
        self._w, self._h = width, height
        self._fail_after = fail_after
        self._loop = loop
        self._i = 0
        self._open = False
        self.reads = 0

    def open(self, camera_id: int, config: CameraConfig) -> None:
        self._open = True
        self.reads = 0

    def close(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def read(self) -> tuple[bool, object, int, int]:
        if not self._open:
            return False, None, 0, 0
        self.reads += 1
        if self._fail_after is not None and self.reads > self._fail_after:
            return False, None, 0, 0            # simulated grab failure
        if self._i >= len(self._frames):
            if not self._loop:
                return False, None, 0, 0
            self._i = 0
        data = self._frames[self._i]
        self._i += 1
        return True, data, self._w, self._h


class OpenCVCaptureBackend:
    """Real capture via OpenCV. Lazily imports ``cv2``.

    ``pipeline`` (optional) is a GStreamer string for Jetson CSI cameras; when
    set, it is opened with ``cv2.CAP_GSTREAMER`` instead of a device index, so
    CSI support needs no change to CameraManager.
    """

    def __init__(self, pipeline: str | None = None) -> None:
        self._pipeline = pipeline
        self._cap = None

    def open(self, camera_id: int, config: CameraConfig) -> None:
        try:
            import cv2                                  # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise CameraError("OpenCV not available", {"error": str(exc)}) from exc
        try:
            if self._pipeline:
                self._cap = cv2.VideoCapture(self._pipeline, cv2.CAP_GSTREAMER)
            else:
                self._cap = cv2.VideoCapture(camera_id)
            if not self._cap or not self._cap.isOpened():
                raise CameraError("failed to open camera",
                                  {"camera_id": camera_id})
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
            self._cap.set(cv2.CAP_PROP_FPS, config.target_fps)
        except CameraError:
            raise
        except Exception as exc:                        # noqa: BLE001
            raise CameraError("error opening camera",
                              {"error": str(exc)}) from exc

    def read(self) -> tuple[bool, object, int, int]:
        if self._cap is None:
            return False, None, 0, 0
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return False, None, 0, 0
        h, w = frame.shape[0], frame.shape[1]
        return True, frame, int(w), int(h)

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            finally:
                self._cap = None

    def is_open(self) -> bool:
        return self._cap is not None


# ===========================================================================
#  Camera manager
# ===========================================================================
class CameraManager:
    """Captures frames on a dedicated thread and delivers them to a FrameBuffer,
    reporting lifecycle through the injected VisionManager seams.

    The ``vision_manager`` is typed structurally (duck-typed) via the small
    ``_VisionSeam`` protocol so this module does not import VisionManager and
    therefore cannot create a circular dependency or modify Stage 1.
    """

    def __init__(self,
                 vision_manager: "_VisionSeam",
                 config: CameraConfig,
                 selector: CameraSelector,
                 buffer: FrameBuffer,
                 backend: CaptureBackend,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._vm = vision_manager
        self._cfg = config
        self._selector = selector
        self._buffer = buffer
        self._backend = backend
        self._clock = clock
        self._sleep = sleep

        self._lock = threading.RLock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_index = 0
        self._camera_id = config.camera_id
        self._reconnect_attempts = 0
        # FPS measurement.
        self._fps_window_start = 0.0
        self._fps_window_count = 0
        self._measured_fps = 0.0

    # ------------------------------------------------------------ lifecycle
    def open(self, camera_id: int | None = None) -> None:
        """Select + open a camera and announce CAMERA_CONNECTED. Raises
        CameraError if the camera cannot be opened."""
        with self._lock:
            cam = self._resolve_camera(camera_id)
            self._camera_id = cam.camera_id
            self._backend.open(cam.camera_id, self._cfg)
            self._reconnect_attempts = 0
        self._vm.on_camera_connected(self._camera_id)
        log.info("camera %d opened", self._camera_id)

    def start(self) -> None:
        """Begin capturing on a dedicated daemon thread."""
        with self._lock:
            if self._running.is_set():
                return
            self._running.set()
            self._fps_window_start = self._clock()
            self._fps_window_count = 0
            self._thread = threading.Thread(target=self._capture_loop,
                                            name="camera-capture", daemon=True)
            self._thread.start()
        log.info("camera capture started")

    def stop(self) -> None:
        """Stop the capture thread and close the camera."""
        with self._lock:
            was_running = self._running.is_set()
            self._running.clear()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
        with self._lock:
            self._backend.close()
        if was_running:
            self._vm.on_camera_disconnected("stopped")
        log.info("camera capture stopped")

    def close(self) -> None:
        """Alias for stop() for symmetry with open()."""
        self.stop()

    # ------------------------------------------------------------ switching
    def switch_camera(self, camera_id: int) -> None:
        """Safely switch to another camera without losing the capture thread:
        validate → stop backend → open new → continue capturing."""
        if not self._selector.validate(camera_id):
            raise CameraError("cannot switch: camera unavailable",
                              {"camera_id": camera_id})
        with self._lock:
            self._backend.close()
            self._vm.on_camera_disconnected("switching")
            cam = self._selector.select(camera_id)
            self._camera_id = cam.camera_id
            self._backend.open(cam.camera_id, self._cfg)
            self._reconnect_attempts = 0
        self._vm.on_camera_connected(self._camera_id)
        log.info("switched to camera %d", camera_id)

    # ------------------------------------------------------------- capture
    def _capture_loop(self) -> None:
        """Dedicated capture thread. Reads frames, timestamps them, pushes to
        the buffer, measures FPS, and reconnects on failure. If it exits due to
        an unrecoverable disconnect, it clears the running flag so ``is_running``
        reflects reality."""
        frame_interval = 1.0 / max(1, self._cfg.target_fps)
        while self._running.is_set():
            ok, data, w, h = self._backend.read()
            if not ok:
                if not self._handle_disconnect():
                    # Unrecoverable: mark ourselves stopped and leave.
                    self._running.clear()
                    break
                continue

            now = self._clock()
            with self._lock:
                idx = self._frame_index
                self._frame_index += 1
            self._buffer.push(Frame(
                data=data, index=idx, timestamp=now,
                width=w, height=h, camera_id=self._camera_id))
            self._update_fps(now)

            # Pace the loop toward target FPS without busy-spinning.
            elapsed = self._clock() - now
            remaining = frame_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)

    def _handle_disconnect(self) -> bool:
        """Camera read failed. Announce, then try to reconnect per config.
        Returns True to keep the loop alive (reconnecting), False to exit."""
        self._vm.on_camera_disconnected("read failure")
        if not self._cfg.auto_reconnect:
            log.warning("camera disconnected; auto_reconnect disabled")
            return False

        while self._running.is_set():
            self._reconnect_attempts += 1
            if (self._cfg.max_reconnect_attempts
                    and self._reconnect_attempts > self._cfg.max_reconnect_attempts):
                log.error("camera reconnect attempts exhausted (%d)",
                          self._reconnect_attempts)
                return False
            log.info("reconnecting camera (attempt %d) in %.1fs",
                     self._reconnect_attempts, self._cfg.reconnect_interval_s)
            self._sleep(self._cfg.reconnect_interval_s)
            try:
                self._backend.close()
                self._backend.open(self._camera_id, self._cfg)
                if self._backend.is_open():
                    self._reconnect_attempts = 0
                    self._vm.on_camera_connected(self._camera_id)
                    log.info("camera reconnected")
                    return True
            except CameraError:
                continue        # keep retrying
        return False

    # -------------------------------------------------------------- helpers
    def _resolve_camera(self, camera_id: int | None) -> CameraInfo:
        if camera_id is not None:
            return self._selector.select(camera_id)
        if self._selector.selected is not None:
            return self._selector.selected
        return self._selector.select_default()

    def _update_fps(self, now: float) -> None:
        """Measure capture FPS over ~1s windows and report to VisionContext."""
        self._fps_window_count += 1
        window = now - self._fps_window_start
        if window >= 1.0:
            self._measured_fps = self._fps_window_count / window
            self._fps_window_start = now
            self._fps_window_count = 0
            self._vm.update_metrics(capture_fps=round(self._measured_fps, 2))

    # -------------------------------------------------------------- readonly
    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_open(self) -> bool:
        return self._backend.is_open()

    @property
    def camera_id(self) -> int:
        with self._lock:
            return self._camera_id

    @property
    def measured_fps(self) -> float:
        return self._measured_fps

    @property
    def frame_buffer(self) -> FrameBuffer:
        return self._buffer


# Structural type for the VisionManager seams CameraManager uses. Declared here
# (not imported) so this module never depends on or modifies Stage 1.
@runtime_checkable
class _VisionSeam(Protocol):
    def on_camera_connected(self, camera_id: int | None = None) -> None: ...
    def on_camera_disconnected(self, reason: str = "") -> None: ...
    def update_metrics(self, capture_fps: float | None = None,
                       processing_fps: float | None = None) -> None: ...
