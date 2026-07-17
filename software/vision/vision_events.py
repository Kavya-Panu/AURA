"""
vision/vision_events.py
=======================
Mapping between the Vision System's readable event names and the core
:class:`RobotEvent` bus vocabulary. Like the behavior/mode/voice layers, the
Vision System does NOT invent a parallel event system - it publishes onto the
existing Event Bus.

Detection events (FACE_FOUND, PHONE_DETECTED, ...) already exist in
``core.constants`` from earlier layers, so we reuse them. Stage 1 added only the
five lifecycle/camera events that had no core equivalent. The spec's alias
names PHONE_REMOVED / PERSON_FOUND map onto the existing PHONE_GONE /
PERSON_RETURNED so downstream subscribers stay consistent.
"""
from __future__ import annotations

from enum import Enum

from core.constants import RobotEvent


class VisionEvent(Enum):
    """Readable Vision event names -> the core RobotEvent actually published."""
    # ---- lifecycle ----
    VISION_STARTED = RobotEvent.VISION_STARTED
    VISION_STOPPED = RobotEvent.VISION_STOPPED
    VISION_ERROR = RobotEvent.VISION_ERROR
    VISION_RESULT = RobotEvent.VISION_RESULT
    # ---- camera ----
    CAMERA_CONNECTED = RobotEvent.CAMERA_CONNECTED
    CAMERA_DISCONNECTED = RobotEvent.CAMERA_DISCONNECTED
    # ---- detections (reused from core; produced by FUTURE detector stages) ----
    FACE_FOUND = RobotEvent.FACE_FOUND
    FACE_LOST = RobotEvent.FACE_LOST
    PHONE_DETECTED = RobotEvent.PHONE_DETECTED
    PHONE_REMOVED = RobotEvent.PHONE_GONE          # spec alias -> core PHONE_GONE
    PERSON_FOUND = RobotEvent.PERSON_RETURNED      # spec alias -> core PERSON_RETURNED
    PERSON_LEFT = RobotEvent.PERSON_LEFT


#: Convenience: the RobotEvent each VisionEvent resolves to.
def robot_event(event: VisionEvent) -> RobotEvent:
    """Return the core RobotEvent a VisionEvent publishes as."""
    return event.value
