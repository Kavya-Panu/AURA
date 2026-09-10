"""
integration/brain_hardware_bridge.py
====================================
Event-driven bridge between AURA's text-only BrainManager and its ESP32 face.

It does not call the serial port or BrainManager directly:
  * BRAIN_STARTED -> THINK expression
  * ANSWER_READY  -> emotion selected from the answer text/mode
  * BRAIN_FAILED  -> ERROR expression

The bridge emits EMOTION_CHANGED, and HardwareManager remains the only module
that can cross the physical hardware boundary.
"""
from __future__ import annotations

import threading

from brain import brain_events
from core.constants import Emotion, RobotEvent
from core.event_bus import Event, EventBus
from core.logger import get_logger
from speech.emotion_mapper import EmotionMapper

log = get_logger("integration.brain_hardware")


class BrainHardwareBridge:
    """Turns brain lifecycle/results into face-expression events."""

    name = "brain_hardware_bridge"

    def __init__(self, event_bus: EventBus,
                 emotion_mapper: EmotionMapper | None = None) -> None:
        self._bus = event_bus
        self._mapper = emotion_mapper or EmotionMapper()
        self._sub_ids: list[int] = []
        self._lock = threading.RLock()
        self._current_mode = "ASSISTANT"

    def initialize(self) -> None:
        """No physical resource is owned by this bridge."""

    def start(self) -> None:
        if self._sub_ids:
            return

        # Record mode before BrainManager handles the same question.
        self._sub_ids.append(self._bus.subscribe(
            RobotEvent.QUESTION_RECEIVED,
            self._on_question,
            priority=100,
        ))
        self._sub_ids.append(self._bus.subscribe(
            brain_events.BRAIN_STARTED,
            self._on_brain_started,
            priority=50,
        ))
        self._sub_ids.append(self._bus.subscribe(
            brain_events.ANSWER_READY,
            self._on_answer_ready,
            priority=50,
        ))
        self._sub_ids.append(self._bus.subscribe(
            brain_events.BRAIN_FAILED,
            self._on_brain_failed,
            priority=50,
        ))
        log.info("brain/hardware bridge started")

    def stop(self) -> None:
        for sub_id in self._sub_ids:
            self._bus.unsubscribe(sub_id)
        self._sub_ids.clear()
        log.info("brain/hardware bridge stopped")

    def health_check(self) -> bool:
        return bool(self._sub_ids)

    def _on_question(self, event: Event) -> None:
        mode = str((event.data or {}).get("mode") or "ASSISTANT").upper()
        with self._lock:
            self._current_mode = mode

    def _on_brain_started(self, _event: Event) -> None:
        self._emit_emotion(Emotion.THINKING.value)

    def _on_answer_ready(self, event: Event) -> None:
        data = event.data or {}
        if not bool(data.get("success", True)):
            self._emit_emotion(Emotion.ERROR.value)
            return

        text = str(data.get("text") or "")
        with self._lock:
            mode = self._current_mode

        style = self._mapper.map(text, mode=mode)
        self._emit_emotion(style.emotion)

    def _on_brain_failed(self, _event: Event) -> None:
        self._emit_emotion(Emotion.ERROR.value)

    def _emit_emotion(self, token: str) -> None:
        self._bus.emit(
            RobotEvent.EMOTION_CHANGED,
            {"emotion": token},
            source=self.name,
        )
