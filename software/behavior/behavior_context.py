"""
behavior/behavior_context.py
============================
The world model the Behavior System reasons over. It is the single mutable
snapshot of "what is true right now", updated by perception events and read by
behaviors when they decide whether they can/should run.

Thread-safe: perception threads (camera, voice) update it while the manager
reads it. All access goes through the lock; :meth:`snapshot` returns an
immutable copy so a behavior can reason without holding the lock.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any

from core.constants import Emotion, RobotState
from .behavior_types import BehaviorType, Priority


@dataclass(frozen=True)
class ContextSnapshot:
    """Immutable point-in-time view of the context (what behaviors receive)."""
    robot_state: RobotState
    emotion: Emotion
    focus_active: bool
    timer_remaining_s: float
    phone_detected: bool
    person_present: bool
    battery_level: float           # 0..1
    battery_charging: bool
    current_behavior: BehaviorType | None
    previous_behavior: BehaviorType | None
    current_priority: Priority
    conversation_active: bool
    current_task: str | None
    extra: dict[str, Any]
    updated_at: float


class BehaviorContext:
    """Mutable, lock-guarded world model. Perception writes; behaviors read."""

    def __init__(self, robot_state: RobotState) -> None:
        self._lock = threading.RLock()
        self._robot_state = robot_state
        self._emotion = Emotion.NORMAL
        self._focus_active = False
        self._timer_remaining_s = 0.0
        self._phone_detected = False
        self._person_present = False
        self._battery_level = 1.0
        self._battery_charging = False
        self._current_behavior: BehaviorType | None = None
        self._previous_behavior: BehaviorType | None = None
        self._current_priority = Priority.BACKGROUND
        self._conversation_active = False
        self._current_task: str | None = None
        self._extra: dict[str, Any] = {}

    # --------------------------------------------------------------- updates
    def update(self, **fields: Any) -> None:
        """Set one or more context fields by name (e.g.
        ``ctx.update(phone_detected=True, person_present=True)``). Unknown
        keys go into ``extra`` for forward-compatibility."""
        with self._lock:
            for key, value in fields.items():
                attr = f"_{key}"
                if hasattr(self, attr):
                    setattr(self, attr, value)
                else:
                    self._extra[key] = value

    def set_current_behavior(self, behavior: BehaviorType | None,
                             priority: Priority) -> None:
        with self._lock:
            self._previous_behavior = self._current_behavior
            self._current_behavior = behavior
            self._current_priority = priority

    def set_state(self, state: RobotState) -> None:
        with self._lock:
            self._robot_state = state

    # ----------------------------------------------------------------- reads
    def snapshot(self) -> ContextSnapshot:
        """Return an immutable copy for lock-free reasoning."""
        with self._lock:
            return ContextSnapshot(
                robot_state=self._robot_state,
                emotion=self._emotion,
                focus_active=self._focus_active,
                timer_remaining_s=self._timer_remaining_s,
                phone_detected=self._phone_detected,
                person_present=self._person_present,
                battery_level=self._battery_level,
                battery_charging=self._battery_charging,
                current_behavior=self._current_behavior,
                previous_behavior=self._previous_behavior,
                current_priority=self._current_priority,
                conversation_active=self._conversation_active,
                current_task=self._current_task,
                extra=dict(self._extra),
                updated_at=time.monotonic(),
            )

    def with_overrides(self, **fields: Any) -> ContextSnapshot:
        """A snapshot with some fields overridden (handy for tests/what-ifs)."""
        return replace(self.snapshot(), **fields)
