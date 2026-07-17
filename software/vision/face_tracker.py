"""
vision/face_tracker.py
======================
Face tracking (Stage 3). A SEPARATE module from the face detector: it consumes
``FACE_FOUND`` events off the Event Bus, maintains stable tracking IDs across
frames, estimates a normalized face position, smooths it, and publishes
``FACE_TRACKED`` and ``FACE_POSITION``.

It is completely independent of MediaPipe/YOLO - it only reacts to bus events,
so it never imports the detectors or any model. It does NOT control servos or
move hardware; a future servo controller subscribes to ``FACE_POSITION``.

Normalized position convention (per spec):
    x = -1.0 (far left) ... +1.0 (far right)
    y = -1.0 (top)      ... +1.0 (bottom)
computed from the face-box center relative to the frame, then EMA-smoothed.

Tracking IDs are assigned by nearest-centroid matching between consecutive
frames (no external tracker dependency), with a small lost-frame tolerance so
brief detection gaps don't churn IDs.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from core.constants import RobotEvent
from core.event_bus import Event, EventBus
from core.logger import get_logger


log = get_logger("vision.face_tracker")


@dataclass
class _Track:
    """Internal tracking state for one face."""
    track_id: int
    x: float                 # smoothed normalized x (-1..1)
    y: float                 # smoothed normalized y (-1..1)
    confidence: float
    last_seen: float = field(default_factory=time.monotonic)
    misses: int = 0


class FaceTracker:
    """Turns FACE_FOUND detections into stable, smoothed, normalized tracks.

    Satisfies the Stage-1 Detector protocol so it can be registered with the
    VisionManager, but it does no inference - it is a pure event transformer.
    """

    name = "face_tracker"

    def __init__(self, event_bus: EventBus,
                 smoothing: float = 0.4,
                 match_distance: float = 0.35,
                 max_misses: int = 5) -> None:
        self._bus = event_bus
        self._alpha = max(0.0, min(1.0, smoothing))     # EMA factor
        self._match_distance = match_distance
        self._max_misses = max_misses

        self._lock = threading.RLock()
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1
        self._sub_id: int | None = None

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        pass

    def start(self) -> None:
        if self._sub_id is None:
            self._sub_id = self._bus.subscribe(
                RobotEvent.FACE_FOUND, self._on_faces, priority=40)
            # Also clear tracks when the detector reports all faces lost.
            self._lost_sub = self._bus.subscribe(
                RobotEvent.FACE_LOST, self._on_lost, priority=40)
        log.info("face tracker started")

    def stop(self) -> None:
        if self._sub_id is not None:
            self._bus.unsubscribe(self._sub_id)
            self._bus.unsubscribe(getattr(self, "_lost_sub", -1))
            self._sub_id = None
        with self._lock:
            self._tracks.clear()

    def health_check(self) -> bool:
        return self._sub_id is not None

    # ------------------------------------------------------------- handlers
    def _on_faces(self, event: Event) -> None:
        faces = event.data.get("faces", [])
        frame = event.data.get("frame", {})
        fw = max(1, int(frame.get("width", 0)) or 1)
        fh = max(1, int(frame.get("height", 0)) or 1)

        # Compute normalized centers for each incoming face.
        incoming: list[tuple[float, float, float]] = []
        for f in faces:
            box = f.get("box", [0, 0, 0, 0])
            cx = box[0] + box[2] / 2.0
            cy = box[1] + box[3] / 2.0
            nx = (cx / fw) * 2.0 - 1.0
            ny = (cy / fh) * 2.0 - 1.0
            incoming.append((_clamp(nx), _clamp(ny),
                             float(f.get("confidence", 0.0))))

        with self._lock:
            self._match_and_update(incoming)
            tracks_snapshot = [
                {"id": t.track_id, "x": round(t.x, 4), "y": round(t.y, 4),
                 "confidence": round(t.confidence, 3)}
                for t in self._tracks.values() if t.misses == 0]
            primary = self._primary_track()

        if tracks_snapshot:
            self._bus.emit(RobotEvent.FACE_TRACKED,
                           {"tracks": tracks_snapshot,
                            "frame_index": event.data.get("frame_index")},
                           source=self.name)
        if primary is not None:
            self._bus.emit(RobotEvent.FACE_POSITION,
                           {"id": primary.track_id,
                            "x": round(primary.x, 4), "y": round(primary.y, 4),
                            "confidence": round(primary.confidence, 3)},
                           source=self.name)

    def _on_lost(self, event: Event) -> None:
        with self._lock:
            self._tracks.clear()

    # -------------------------------------------------------- matching logic
    def _match_and_update(self, incoming: list[tuple[float, float, float]]) -> None:
        unmatched = set(self._tracks)
        for nx, ny, conf in incoming:
            best_id, best_dist = None, self._match_distance
            for tid in unmatched:
                t = self._tracks[tid]
                d = ((t.x - nx) ** 2 + (t.y - ny) ** 2) ** 0.5
                if d < best_dist:
                    best_id, best_dist = tid, d
            if best_id is not None:
                t = self._tracks[best_id]
                t.x = _ema(t.x, nx, self._alpha)
                t.y = _ema(t.y, ny, self._alpha)
                t.confidence = conf
                t.last_seen = time.monotonic()
                t.misses = 0
                unmatched.discard(best_id)
            else:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = _Track(tid, nx, ny, conf)

        # Age out tracks that weren't matched this frame.
        for tid in list(unmatched):
            t = self._tracks[tid]
            t.misses += 1
            if t.misses > self._max_misses:
                del self._tracks[tid]

    def _primary_track(self) -> _Track | None:
        """The most central, confident visible track (a servo would follow it)."""
        visible = [t for t in self._tracks.values() if t.misses == 0]
        if not visible:
            return None
        return min(visible, key=lambda t: (t.x ** 2 + t.y ** 2) - t.confidence)

    # ------------------------------------------------------------- readonly
    @property
    def track_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tracks.values() if t.misses == 0)


def _clamp(v: float) -> float:
    return -1.0 if v < -1.0 else 1.0 if v > 1.0 else v


def _ema(old: float, new: float, alpha: float) -> float:
    """Exponential moving average smoothing."""
    return (1 - alpha) * old + alpha * new
