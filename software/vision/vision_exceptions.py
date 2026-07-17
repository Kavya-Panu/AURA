"""
vision/vision_exceptions.py
===========================
Vision-System-specific exceptions, rooted in the project's ``AuraError`` so any
caller can catch "anything AURA" with one clause while still targeting precise
failures.

Stage 1 is architecture only: no detection algorithms exist yet, so these
exceptions describe *structural* failures (camera, detector registration,
configuration), not detection failures.
"""
from __future__ import annotations

from core.exceptions import AuraError


class VisionError(AuraError):
    """Base class for all Vision System errors."""


class CameraError(VisionError):
    """Camera unavailable, disconnected, or failed to open."""


class DetectorError(VisionError):
    """A detector failed to initialize, run, or shut down."""


class DetectorRegistrationError(VisionError):
    """Invalid detector registration (duplicate name, bad object)."""


class VisionConfigurationError(VisionError):
    """Invalid Vision System configuration values."""
