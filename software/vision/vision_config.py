"""
vision/vision_config.py
=======================
All configurable values for the Vision System. Pure data (dataclasses); no
behaviour and no magic numbers anywhere else in the package.

Stage 1 defines the full configuration surface future detector stages will
consume (camera, processing cadence, per-detector toggles), but nothing here
opens a camera or runs a model - it is only settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .vision_exceptions import VisionConfigurationError


@dataclass
class CameraConfig:
    """Camera capture settings (consumed by a future camera backend)."""
    camera_id: int = 0                 # OS camera index / device id
    width: int = 640
    height: int = 480
    target_fps: int = 30               # requested capture frame rate
    auto_reconnect: bool = True
    reconnect_interval_s: float = 3.0
    max_reconnect_attempts: int = 0    # 0 = retry forever


@dataclass
class ProcessingConfig:
    """How often heavy detection runs relative to capture."""
    detect_every_n_frames: int = 5     # run detectors every Nth captured frame
    max_processing_fps: int = 15       # cap detector throughput
    downscale: float = 1.0             # 1.0 = full res; <1 downscales for speed
    drop_frames_when_busy: bool = True # skip frames rather than queue them


@dataclass
class DetectorToggles:
    """Which detectors are active. Detectors themselves arrive in later stages;
    these flags let the manager register/enable them declaratively now."""
    face: bool = True
    person: bool = True
    phone: bool = True
    gesture: bool = False


@dataclass
class VisionConfig:
    """Top-level Vision System configuration."""
    enabled: bool = True
    camera: CameraConfig = field(default_factory=CameraConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    detectors: DetectorToggles = field(default_factory=DetectorToggles)

    # Publish a heartbeat/health event this often (0 disables).
    health_interval_s: float = 10.0

    def validate(self) -> None:
        """Raise VisionConfigurationError on the first invalid value."""
        if self.camera.width <= 0 or self.camera.height <= 0:
            raise VisionConfigurationError(
                "camera dimensions must be positive",
                {"width": self.camera.width, "height": self.camera.height})
        if not (1 <= self.camera.target_fps <= 240):
            raise VisionConfigurationError(
                "camera.target_fps must be in 1..240",
                {"fps": self.camera.target_fps})
        if self.processing.detect_every_n_frames < 1:
            raise VisionConfigurationError(
                "processing.detect_every_n_frames must be >= 1")
        if self.processing.max_processing_fps < 1:
            raise VisionConfigurationError(
                "processing.max_processing_fps must be >= 1")
        if not (0.1 <= self.processing.downscale <= 1.0):
            raise VisionConfigurationError(
                "processing.downscale must be in 0.1..1.0",
                {"downscale": self.processing.downscale})
        if self.camera.reconnect_interval_s < 0:
            raise VisionConfigurationError(
                "camera.reconnect_interval_s must be >= 0")
