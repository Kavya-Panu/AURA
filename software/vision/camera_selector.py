"""
vision/camera_selector.py
=========================
Camera discovery and selection. Enumerates available cameras, returns metadata,
picks a default, validates availability, and safely switches cameras - all
without importing OpenCV directly.

Discovery is delegated to a :class:`CameraProbe` (dependency injection):
* :class:`OpenCVCameraProbe` - real; lazily imports ``cv2`` and probes indices.
* :class:`FakeCameraProbe`   - scripted device list; for tests / no hardware.

This keeps camera *selection policy* (which one, is it valid, switch safely)
separate from camera *access* (opening a stream), following SRP.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, runtime_checkable

from core.logger import get_logger
from .vision_exceptions import CameraError

log = get_logger("vision.selector")


class CameraKind(Enum):
    """Physical camera category. CSI is the Jetson ribbon-cable camera."""
    LAPTOP_WEBCAM = auto()
    USB = auto()
    CSI = auto()             # Jetson / Raspberry Pi ribbon camera (future)
    UNKNOWN = auto()


@dataclass(frozen=True)
class CameraInfo:
    """Metadata describing one discovered camera."""
    camera_id: int
    name: str = ""
    kind: CameraKind = CameraKind.UNKNOWN
    backend: str = ""                 # e.g. "v4l2", "avfoundation", "csi"
    available: bool = True
    width: int = 0
    height: int = 0

    def __str__(self) -> str:         # friendly log line
        return (f"[{self.camera_id}] {self.name or 'camera'} "
                f"({self.kind.name.lower()}, {self.backend or 'default'})")


@runtime_checkable
class CameraProbe(Protocol):
    """Discovers cameras. Real probe uses OpenCV; fake probe is scripted."""
    def discover(self) -> list[CameraInfo]: ...
    def is_available(self, camera_id: int) -> bool: ...


class FakeCameraProbe:
    """Scripted probe for tests. Holds a fixed device list that can be mutated
    to simulate plug/unplug."""

    def __init__(self, cameras: list[CameraInfo] | None = None) -> None:
        self._cameras = list(cameras or [])

    def set_cameras(self, cameras: list[CameraInfo]) -> None:
        self._cameras = list(cameras)

    def discover(self) -> list[CameraInfo]:
        return list(self._cameras)

    def is_available(self, camera_id: int) -> bool:
        return any(c.camera_id == camera_id and c.available
                   for c in self._cameras)


class OpenCVCameraProbe:
    """Real probe. Lazily imports ``cv2`` and tries to open a range of indices
    to see which respond. Kept dependency-light so importing this module never
    requires OpenCV."""

    def __init__(self, max_index: int = 8) -> None:
        self._max_index = max_index

    def discover(self) -> list[CameraInfo]:
        try:
            import cv2                                  # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise CameraError("OpenCV not available for discovery",
                              {"error": str(exc)}) from exc
        found: list[CameraInfo] = []
        for idx in range(self._max_index):
            cap = None
            try:
                cap = cv2.VideoCapture(idx)
                if cap is not None and cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                    kind = CameraKind.LAPTOP_WEBCAM if idx == 0 else CameraKind.USB
                    found.append(CameraInfo(
                        camera_id=idx, name=f"camera{idx}", kind=kind,
                        backend="opencv", available=True, width=w, height=h))
            except Exception:                           # noqa: BLE001
                pass
            finally:
                if cap is not None:
                    cap.release()
        return found

    def is_available(self, camera_id: int) -> bool:
        try:
            import cv2
        except Exception:                               # noqa: BLE001
            return False
        cap = None
        try:
            cap = cv2.VideoCapture(camera_id)
            return bool(cap is not None and cap.isOpened())
        except Exception:                               # noqa: BLE001
            return False
        finally:
            if cap is not None:
                cap.release()


class CameraSelector:
    """Discovers, validates, selects and switches cameras. Thread-safe."""

    def __init__(self, probe: CameraProbe,
                 preferred_id: int | None = None) -> None:
        self._probe = probe
        self._lock = threading.RLock()
        self._cameras: list[CameraInfo] = []
        self._selected: CameraInfo | None = None
        self._preferred_id = preferred_id

    # ------------------------------------------------------------- discovery
    def discover(self) -> list[CameraInfo]:
        """(Re)enumerate all connected cameras and cache the result."""
        cameras = self._probe.discover()
        with self._lock:
            self._cameras = cameras
        log.info("discovered %d camera(s): %s",
                 len(cameras), ", ".join(str(c) for c in cameras) or "none")
        return list(cameras)

    @property
    def cameras(self) -> list[CameraInfo]:
        with self._lock:
            return list(self._cameras)

    def get_info(self, camera_id: int) -> CameraInfo | None:
        with self._lock:
            return next((c for c in self._cameras
                         if c.camera_id == camera_id), None)

    # ------------------------------------------------------------- selection
    def select_default(self) -> CameraInfo:
        """Pick the default camera: the preferred id if present & available,
        else the first available camera. Raises CameraError if none."""
        with self._lock:
            if not self._cameras:
                self._cameras = self._probe.discover()
            candidates = [c for c in self._cameras if c.available]
            if not candidates:
                raise CameraError("no cameras available")
            chosen: CameraInfo | None = None
            if self._preferred_id is not None:
                chosen = next((c for c in candidates
                               if c.camera_id == self._preferred_id), None)
            if chosen is None:
                chosen = candidates[0]
            self._selected = chosen
        log.info("selected default camera %s", chosen)
        return chosen

    def select(self, camera_id: int) -> CameraInfo:
        """Select a specific camera by id, validating availability first."""
        if not self.validate(camera_id):
            raise CameraError("requested camera is not available",
                              {"camera_id": camera_id})
        info = self.get_info(camera_id) or CameraInfo(camera_id=camera_id)
        with self._lock:
            self._selected = info
        log.info("selected camera %s", info)
        return info

    def validate(self, camera_id: int) -> bool:
        """Return True if ``camera_id`` is currently openable."""
        return self._probe.is_available(camera_id)

    @property
    def selected(self) -> CameraInfo | None:
        with self._lock:
            return self._selected
