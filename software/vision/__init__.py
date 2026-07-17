"""
vision - AURA's Vision System (Stage 1: architecture only).

Stage 1 provides the coordinator, context, config, events, result type and
exceptions that future detector stages (face / person / phone / gesture) plug
into. No camera access and no detection algorithms exist yet.

Usage::

    from vision import VisionManager, VisionConfig
    vision = VisionManager(bus, VisionConfig())
    lifecycle.register(vision)          # it is a core Module
    # later stages: vision.register_detector(FaceDetector(...))
"""
from .vision_config import VisionConfig
from .vision_context import VisionContext, VisionSnapshot
from .vision_events import VisionEvent, robot_event
from .vision_manager import Detector, VisionManager
from .vision_result import (
    BoundingBox,
    Detection,
    DetectionKind,
    VisionResult,
)

__all__ = [
    "VisionManager",
    "Detector",
    "VisionConfig",
    "VisionContext",
    "VisionSnapshot",
    "VisionEvent",
    "robot_event",
    "VisionResult",
    "Detection",
    "DetectionKind",
    "BoundingBox",
]
