"""
vision/vision_result.py
=======================
The generic result type future detectors return. Stage 1 defines the shape; no
detector produces one yet.

A detector (face/phone/person/gesture, arriving in later stages) processes a
frame and returns zero or more :class:`Detection` objects wrapped in a
:class:`VisionResult`. Keeping this generic means the VisionManager and the
Event Bus never need to know *which* detector produced a result.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class DetectionKind(Enum):
    """What a detection represents. Extend as detectors are added."""
    FACE = auto()
    PERSON = auto()
    PHONE = auto()
    GESTURE = auto()
    OBJECT = auto()          # generic fallback
    UNKNOWN = auto()


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in pixel coordinates."""
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Detection:
    """A single thing a detector found in one frame."""
    kind: DetectionKind
    confidence: float                       # 0..1
    box: BoundingBox | None = None
    label: str = ""                         # e.g. "cell phone"
    track_id: int | None = None             # stable id across frames (future)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisionResult:
    """The generic output of one detector for one frame.

    Attributes:
        detector: Name of the producing detector ("face", "phone", ...).
        detections: Zero or more detections found in the frame.
        frame_index: Monotonic index of the processed frame.
        processing_ms: Wall-clock time the detector took on this frame.
        timestamp: ``time.time()`` when the result was produced.
    """
    detector: str
    detections: tuple[Detection, ...] = ()
    frame_index: int = 0
    processing_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def has_detections(self) -> bool:
        return len(self.detections) > 0

    def of_kind(self, kind: DetectionKind) -> tuple[Detection, ...]:
        """Filter detections by kind."""
        return tuple(d for d in self.detections if d.kind is kind)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form for logging / event payloads."""
        return {
            "detector": self.detector,
            "count": len(self.detections),
            "frame_index": self.frame_index,
            "processing_ms": round(self.processing_ms, 3),
            "timestamp": self.timestamp,
            "detections": [
                {"kind": d.kind.name, "confidence": round(d.confidence, 3),
                 "label": d.label, "track_id": d.track_id,
                 "box": None if d.box is None else
                        [d.box.x, d.box.y, d.box.width, d.box.height]}
                for d in self.detections
            ],
        }
