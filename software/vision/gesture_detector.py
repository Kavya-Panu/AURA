"""
vision/gesture_detector.py
==========================
Hand-gesture detection (final Vision stage). Uses MediaPipe Hands on the real
system.

COMPLETELY INDEPENDENT: never imports YOLO or another detector. Inference sits
behind a :class:`GestureBackend` Protocol (dependency injection):
* :class:`MediaPipeHandsBackend` - real; lazily imports ``mediapipe``. It returns
  raw hand landmarks; gesture *classification* is done here so new gestures are
  easy to add without touching the backend.
* :class:`FakeGestureBackend`    - scripted gestures; for tests / no hardware.

Recognises Hand Wave, Raised Hand, Thumbs Up and publishes ``HAND_WAVE``,
``HAND_RAISED``, ``THUMBS_UP``. Adding a gesture = adding one classifier
function to ``GESTURE_CLASSIFIERS`` (Open/Closed). It NEVER executes robot
actions - it only publishes events. Implements the Stage-1 Detector protocol and
reads frames from the Stage-2 FrameBuffer on its own thread.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

from core.constants import RobotEvent
from core.event_bus import EventBus
from core.logger import get_logger

from .frame_buffer import Frame, FrameBuffer
from .vision_config import VisionConfig
from .vision_exceptions import DetectorError

log = get_logger("vision.gesture")


class GestureType(Enum):
    """Recognised gestures. Extend here + add a classifier to support more."""
    WAVE = "HAND_WAVE"
    RAISED_HAND = "HAND_RAISED"
    THUMBS_UP = "THUMBS_UP"


@dataclass(frozen=True)
class HandLandmarks:
    """21 normalized (x, y) hand landmarks (MediaPipe order). z omitted - the
    2D projection is enough for these gestures."""
    points: tuple[tuple[float, float], ...]
    handedness: str = ""              # "Left" / "Right"

    def y(self, i: int) -> float:
        return self.points[i][1]

    def x(self, i: int) -> float:
        return self.points[i][0]


@dataclass
class GestureObservation:
    """A gesture recognised in one frame."""
    gesture: GestureType
    confidence: float


@runtime_checkable
class GestureBackend(Protocol):
    """Returns hand landmarks for a frame. Real impl wraps MediaPipe Hands."""
    def load(self) -> None: ...
    def detect(self, frame: object, width: int, height: int) -> list[HandLandmarks]: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------
#  Gesture classifiers - pure functions over landmarks. Add new gestures here.
#  MediaPipe landmark indices: 0 wrist; thumb tip 4; index tip 8, pip 6;
#  middle tip 12, pip 10; ring tip 16, pip 14; pinky tip 20, pip 18.
# --------------------------------------------------------------------------
def _is_thumbs_up(h: HandLandmarks) -> float:
    """Thumb extended upward, other fingers curled."""
    thumb_up = h.y(4) < h.y(3) < h.y(2)
    folded = all(h.y(tip) > h.y(pip)
                 for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)))
    return 0.9 if (thumb_up and folded) else 0.0


def _is_raised_hand(h: HandLandmarks) -> float:
    """Open palm, all four fingers extended above their PIP joints."""
    extended = all(h.y(tip) < h.y(pip)
                   for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)))
    return 0.85 if extended else 0.0


#: name -> classifier. Wave is temporal, handled separately below.
GESTURE_CLASSIFIERS: dict[GestureType, Callable[[HandLandmarks], float]] = {
    GestureType.THUMBS_UP: _is_thumbs_up,
    GestureType.RAISED_HAND: _is_raised_hand,
}


class FakeGestureBackend:
    """Scripted gesture backend for tests. Each script entry is a list of
    HandLandmarks for that frame (FIFO)."""

    def __init__(self, script: list[list[HandLandmarks]] | None = None) -> None:
        self._script = list(script or [])
        self._i = 0
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def queue(self, hands: list[HandLandmarks]) -> None:
        self._script.append(hands)

    def detect(self, frame: object, width: int, height: int) -> list[HandLandmarks]:
        if not self._script:
            return []
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        return list(self._script[idx])

    def close(self) -> None:
        self.loaded = False


class MediaPipeHandsBackend:
    """Real backend using MediaPipe Hands. Lazily imported."""

    def __init__(self, max_hands: int = 2, min_confidence: float = 0.6) -> None:
        self._max_hands = max_hands
        self._min_conf = min_confidence
        self._hands = None

    def load(self) -> None:
        try:
            import mediapipe as mp                      # lazy import
        except Exception as exc:                        # noqa: BLE001
            raise DetectorError("MediaPipe not available",
                                {"error": str(exc)}) from exc
        self._hands = mp.solutions.hands.Hands(
            max_num_hands=self._max_hands,
            min_detection_confidence=self._min_conf,
            min_tracking_confidence=self._min_conf)

    def detect(self, frame: object, width: int, height: int) -> list[HandLandmarks]:
        if self._hands is None:
            raise DetectorError("MediaPipeHandsBackend.detect before load()")
        results = self._hands.process(frame)            # RGB ndarray
        hands: list[HandLandmarks] = []
        multi = results.multi_hand_landmarks or []
        handed = results.multi_handedness or []
        for i, lm in enumerate(multi):
            pts = tuple((p.x, p.y) for p in lm.landmark)
            label = ""
            if i < len(handed) and handed[i].classification:
                label = handed[i].classification[0].label
            hands.append(HandLandmarks(pts, label))
        return hands

    def close(self) -> None:
        if self._hands is not None:
            try:
                self._hands.close()
            finally:
                self._hands = None


class GestureDetector:
    """Classifies hand gestures and publishes gesture events. Independent of all
    other detectors."""

    name = "gesture"

    def __init__(self, event_bus: EventBus, frame_buffer: FrameBuffer,
                 config: VisionConfig, backend: GestureBackend,
                 wave_min_swings: int = 3, cooldown_s: float = 1.5,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._buffer = frame_buffer
        self._cfg = config
        self._backend = backend
        self._wave_min_swings = wave_min_swings
        self._cooldown_s = cooldown_s
        self._clock = clock

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_index = -1
        self._frame_counter = 0
        # Wave detection: track horizontal direction changes of the wrist.
        self._last_wrist_x: float | None = None
        self._last_dir = 0
        self._swings = 0
        self._last_fire: dict[GestureType, float] = {}

    # ----------------------------------------------------- Detector protocol
    def initialize(self) -> None:
        self._backend.load()
        log.info("gesture detector initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision-gesture",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._backend.close()

    def health_check(self) -> bool:
        return self._running.is_set() and (
            self._thread is not None and self._thread.is_alive())

    # --------------------------------------------------------------- worker
    def _loop(self) -> None:
        every_n = max(1, self._cfg.processing.detect_every_n_frames)
        while self._running.is_set():
            frame = self._buffer.wait_for_frame(since_index=self._last_index,
                                                timeout_s=0.5)
            if frame is None:
                continue
            self._last_index = frame.index
            self._frame_counter += 1
            if self._frame_counter % every_n != 0:
                continue
            try:
                self._process(frame)
            except Exception:                           # noqa: BLE001
                log.exception("gesture detection failed on frame %d", frame.index)

    def _process(self, frame: Frame) -> None:
        hands = self._backend.detect(frame.data, frame.width, frame.height)
        if not hands:
            self._reset_wave()
            return
        hand = hands[0]
        # Static gestures via the classifier registry.
        for gesture, classify in GESTURE_CLASSIFIERS.items():
            conf = classify(hand)
            if conf > 0.0:
                self._fire(gesture, conf, frame.index)
        # Temporal gesture: wave.
        self._update_wave(hand, frame.index)

    def _update_wave(self, hand: HandLandmarks, frame_index: int) -> None:
        wrist_x = hand.x(0)
        if self._last_wrist_x is not None:
            dx = wrist_x - self._last_wrist_x
            direction = 1 if dx > 0.02 else -1 if dx < -0.02 else 0
            if direction != 0 and direction != self._last_dir and self._last_dir != 0:
                self._swings += 1
                if self._swings >= self._wave_min_swings:
                    self._fire(GestureType.WAVE, 0.8, frame_index)
                    self._swings = 0
            if direction != 0:
                self._last_dir = direction
        self._last_wrist_x = wrist_x

    def _reset_wave(self) -> None:
        self._last_wrist_x = None
        self._last_dir = 0
        self._swings = 0

    def _fire(self, gesture: GestureType, confidence: float,
              frame_index: int) -> None:
        now = self._clock()
        if now - self._last_fire.get(gesture, -1e9) < self._cooldown_s:
            return
        self._last_fire[gesture] = now
        self._bus.emit(RobotEvent[gesture.value],
                       {"gesture": gesture.name,
                        "confidence": round(confidence, 3),
                        "frame_index": frame_index},
                       source=self.name)
        log.debug("gesture %s (%.2f)", gesture.name, confidence)
