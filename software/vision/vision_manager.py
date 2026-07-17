"""
vision/vision_manager.py
========================
The Vision System's coordinator (Stage 1: architecture only).

Responsibilities:
* implement the core ``Module`` protocol so the LifecycleManager owns it
  (initialize / start / stop / health_check),
* register / unregister detectors behind a ``Detector`` Protocol,
* maintain the :class:`VisionContext`,
* publish Vision events on the Event Bus,
* provide the seam a future camera/processing loop plugs into
  (``publish_result`` / ``on_camera_connected`` / ``on_camera_disconnected``).

It contains NO camera access and NO detection algorithms. Detectors are objects
that satisfy the ``Detector`` interface; Stage 1 only registers and lifecycles
them - later stages provide real OpenCV/MediaPipe/YOLO implementations without
touching this file (Open/Closed principle).

Thread-safety: registration, lifecycle and result publishing are guarded by a
re-entrant lock; the bus delivers events to subscribers.
"""
from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from core.event_bus import EventBus
from core.logger import get_logger

from .vision_config import VisionConfig
from .vision_context import VisionContext
from .vision_events import VisionEvent, robot_event
from .vision_exceptions import (
    DetectorError,
    DetectorRegistrationError,
    VisionError,
)
from .vision_result import VisionResult

log = get_logger("vision.manager")


@runtime_checkable
class Detector(Protocol):
    """Contract every detector (face/phone/person/gesture) must satisfy.

    Stage 1 defines the interface only; concrete detectors arrive later and are
    registered without modifying the manager.
    """
    name: str

    def initialize(self) -> None:
        """Acquire resources (load a model). May raise VisionError."""
        ...

    def start(self) -> None:
        """Begin detecting."""
        ...

    def stop(self) -> None:
        """Stop detecting and release resources. Safe to call twice."""
        ...

    def health_check(self) -> bool:
        """Return True if the detector is healthy."""
        ...


class VisionManager:
    """Coordinates cameras (future), detectors, context and Vision events."""

    name = "vision"

    def __init__(self, event_bus: EventBus, config: VisionConfig | None = None,
                 context: VisionContext | None = None) -> None:
        self._bus = event_bus
        self._cfg = config or VisionConfig()
        self._cfg.validate()
        self._ctx = context or VisionContext(
            camera_id=self._cfg.camera.camera_id, enabled=self._cfg.enabled)
        self._lock = threading.RLock()
        self._detectors: dict[str, Detector] = {}
        self._started = False

    # =====================================================================
    #  Detector registration (Open/Closed: add detectors, never edit this)
    # =====================================================================
    def register_detector(self, detector: Detector) -> None:
        """Register a detector. If the manager is already running, the detector
        is initialized and started immediately so it joins in progress."""
        if not isinstance(detector, Detector):
            raise DetectorRegistrationError(
                "object does not satisfy the Detector protocol",
                {"object": type(detector).__name__})
        with self._lock:
            if detector.name in self._detectors:
                raise DetectorRegistrationError(
                    "duplicate detector name", {"name": detector.name})
            self._detectors[detector.name] = detector
            already_running = self._started
        log.info("registered detector '%s'", detector.name)

        if already_running:
            try:
                detector.initialize()
                detector.start()
                self._ctx.add_detector(detector.name)
            except Exception as exc:            # noqa: BLE001
                self._fail(f"detector '{detector.name}' failed to join",
                           exc)

    def unregister_detector(self, name: str) -> bool:
        """Stop and remove a detector. Returns True if it existed."""
        with self._lock:
            detector = self._detectors.pop(name, None)
        if detector is None:
            return False
        self._safe_stop(detector)
        self._ctx.remove_detector(name)
        log.info("unregistered detector '%s'", name)
        return True

    def get_detector(self, name: str) -> Detector | None:
        with self._lock:
            return self._detectors.get(name)

    @property
    def detectors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._detectors))

    # =====================================================================
    #  Module protocol (LifecycleManager drives these)
    # =====================================================================
    def initialize(self) -> None:
        """Initialize every registered detector. Fail fast on the first error."""
        with self._lock:
            detectors = list(self._detectors.values())
        for detector in detectors:
            try:
                detector.initialize()
            except Exception as exc:            # noqa: BLE001
                raise VisionError("detector failed to initialize",
                                  {"detector": detector.name}) from exc
        log.info("vision initialised (%d detector(s))", len(detectors))

    def start(self) -> None:
        """Start detectors and announce the Vision System is live."""
        with self._lock:
            if self._started:
                return
            self._started = True
            detectors = list(self._detectors.values())
        self._ctx.set_running(True)
        self._ctx.set_enabled(self._cfg.enabled)
        for detector in detectors:
            try:
                detector.start()
                self._ctx.add_detector(detector.name)
            except Exception as exc:            # noqa: BLE001
                self._fail(f"detector '{detector.name}' failed to start", exc)
        self._emit(VisionEvent.VISION_STARTED,
                   {"detectors": list(self._ctx.active_detectors)})
        log.info("vision started")

    def stop(self) -> None:
        """Stop detectors (reverse order) and announce shutdown."""
        with self._lock:
            if not self._started:
                return
            self._started = False
            detectors = list(reversed(list(self._detectors.values())))
        for detector in detectors:
            self._safe_stop(detector)
            self._ctx.remove_detector(detector.name)
        self._ctx.set_running(False)
        self._ctx.set_camera_connected(False)
        self._emit(VisionEvent.VISION_STOPPED, {})
        log.info("vision stopped")

    def health_check(self) -> bool:
        """Healthy iff running, enabled, and every detector reports healthy."""
        with self._lock:
            if not self._started or not self._ctx.enabled:
                return False
            detectors = list(self._detectors.values())
        for detector in detectors:
            try:
                if not detector.health_check():
                    return False
            except Exception:                   # noqa: BLE001
                return False
        return True

    # =====================================================================
    #  Camera + result seams (a future capture loop calls these)
    # =====================================================================
    def on_camera_connected(self, camera_id: int | None = None) -> None:
        """Record + announce that the camera is available."""
        if camera_id is not None:
            self._ctx.set_camera_id(camera_id)
        self._ctx.set_camera_connected(True)
        self._ctx.clear_error()
        self._emit(VisionEvent.CAMERA_CONNECTED,
                   {"camera_id": camera_id if camera_id is not None
                    else self._cfg.camera.camera_id})

    def on_camera_disconnected(self, reason: str = "") -> None:
        """Record + announce that the camera was lost."""
        self._ctx.set_camera_connected(False)
        self._emit(VisionEvent.CAMERA_DISCONNECTED, {"reason": reason})

    def update_metrics(self, capture_fps: float | None = None,
                       processing_fps: float | None = None) -> None:
        """Let a future loop report measured frame rates into the context."""
        if capture_fps is not None:
            self._ctx.set_capture_fps(capture_fps)
        if processing_fps is not None:
            self._ctx.set_processing_fps(processing_fps)

    def publish_result(self, result: VisionResult) -> None:
        """Publish a detector's :class:`VisionResult` on the bus. Stage 1 has no
        detectors producing results; this is the seam future stages call.

        The manager stays generic: it forwards the raw result under
        ``VISION_RESULT``. Detectors/adapters in later stages emit the specific
        semantic events (FACE_FOUND, PHONE_DETECTED, ...) themselves, keeping the
        manager agnostic to detection meaning (Single Responsibility).
        """
        self._emit(VisionEvent.VISION_RESULT, result.to_dict())

    # =====================================================================
    #  Enable / disable at runtime
    # =====================================================================
    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable vision processing (context flag; loop honours it)."""
        self._ctx.set_enabled(enabled)
        log.debug("vision enabled = %s", enabled)

    @property
    def context(self) -> VisionContext:
        return self._ctx

    @property
    def config(self) -> VisionConfig:
        return self._cfg

    # =====================================================================
    #  Internals
    # =====================================================================
    def _emit(self, event: VisionEvent, data: dict) -> None:
        self._bus.emit(robot_event(event), data, source=self.name)

    def _fail(self, message: str, exc: Exception) -> None:
        log.exception(message)
        self._ctx.set_error(f"{message}: {exc}")
        self._bus.emit(robot_event(VisionEvent.VISION_ERROR),
                       {"message": message, "error": str(exc)},
                       source=self.name)

    @staticmethod
    def _safe_stop(detector: Detector) -> None:
        try:
            detector.stop()
        except Exception:                       # noqa: BLE001
            log.exception("detector '%s' failed to stop cleanly",
                          getattr(detector, "name", "?"))
