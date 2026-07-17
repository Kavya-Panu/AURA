"""
behavior/behavior_base.py
=========================
Abstract base every behavior inherits from. It defines the lifecycle the
BehaviorManager drives and gives sensible no-op defaults so simple behaviors
only override what they need.

Lifecycle (manager-driven):

    can_run(ctx)  -> may this behavior start given the world right now?
    enter()       -> called once when it becomes the active behavior
    execute()     -> called once right after enter (kick off the action)
    update(dt)    -> called every manager tick; return True when finished
    exit()        -> called once when leaving (completed/cancelled/replaced)
    interrupt()   -> paused by a higher-priority behavior (state kept)
    resume()      -> resumed after the interrupter finished
    cancel()      -> hard stop, will not resume

A behavior NEVER touches hardware or state directly. It expresses intent by
publishing events / requesting emotions through the injected ``BehaviorActions``
facade, which the manager provides.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Protocol

from dataclasses import dataclass

from core.constants import Emotion, RobotState
from .behavior_context import ContextSnapshot
from .behavior_types import (
    BehaviorStatus,
    BehaviorType,
    InterruptPolicy,
    Priority,
)


class BehaviorActions(Protocol):
    """The ONLY channel a behavior uses to affect the robot. Implemented by the
    BehaviorManager; keeps behaviors decoupled from bus/state/hardware."""

    def request_emotion(self, emotion: Emotion) -> None: ...
    def request_state(self, state: RobotState, reason: str = "") -> None: ...
    def request_speech(self, text: str) -> None: ...
    def emit(self, event_name: str, **data: object) -> None: ...
    def snapshot(self) -> ContextSnapshot: ...       # read the current world


@dataclass(frozen=True)
class Requirements:
    """Preconditions a behavior needs before it may run."""
    needs_person: bool = False
    needs_focus_active: bool = False
    min_battery: float = 0.0
    allowed_states: frozenset[RobotState] | None = None  # None = any


class Behavior(ABC):
    """Abstract base class for all behaviors."""

    #: The behavior's identity - subclasses set this.
    behavior_type: BehaviorType = BehaviorType.IDLE
    #: How this behavior treats a lower-priority one it is about to displace.
    interrupt_policy: InterruptPolicy = InterruptPolicy.PREEMPT
    #: Optional hard cap; None = no timeout.
    max_duration_s: float | None = None

    def __init__(self, actions: BehaviorActions) -> None:
        self._actions = actions
        self._status = BehaviorStatus.PENDING
        self._lock = threading.RLock()
        self._elapsed = 0.0

    # ------------------------------------------------------------- identity
    def priority(self) -> Priority:
        """Priority used for preemption. Override for non-default tiers."""
        return Priority.NORMAL

    def requirements(self) -> Requirements:
        """Preconditions; override to constrain when this can run."""
        return Requirements()

    def can_run(self, ctx: ContextSnapshot) -> bool:
        """Default gate from :meth:`requirements`. Override for custom logic."""
        req = self.requirements()
        if req.needs_person and not ctx.person_present:
            return False
        if req.needs_focus_active and not ctx.focus_active:
            return False
        if ctx.battery_level < req.min_battery:
            return False
        if req.allowed_states is not None and ctx.robot_state not in req.allowed_states:
            return False
        return True

    # ------------------------------------------------------------- lifecycle
    def enter(self) -> None:
        """Called once when this becomes active. Override to set emotion etc."""

    def execute(self) -> None:
        """Called once after enter to kick off the action. Override."""

    @abstractmethod
    def update(self, dt_s: float) -> bool:
        """Advance the behavior. Return True when it is finished.

        The base tracks elapsed time and enforces ``max_duration_s`` via
        :meth:`tick` - subclasses implement only their own progress logic.
        """

    def exit(self) -> None:
        """Called once when leaving for any reason. Override to clean up."""

    def interrupt(self) -> None:
        """Paused by a higher-priority behavior. Keep state for resume()."""
        with self._lock:
            self._status = BehaviorStatus.PAUSED

    def resume(self) -> None:
        """Resumed after the interrupter finished."""
        with self._lock:
            self._status = BehaviorStatus.RUNNING

    def cancel(self) -> None:
        """Hard stop; will not resume."""
        with self._lock:
            self._status = BehaviorStatus.CANCELLED

    # --------------------------------------------------- manager entry points
    def tick(self, dt_s: float) -> bool:
        """Manager calls this each frame. Handles timeout + status, delegates
        progress to :meth:`update`. Returns True when the behavior should end."""
        with self._lock:
            if self._status not in (BehaviorStatus.RUNNING,
                                    BehaviorStatus.PENDING):
                return self._status in (BehaviorStatus.COMPLETED,
                                        BehaviorStatus.CANCELLED,
                                        BehaviorStatus.TIMED_OUT,
                                        BehaviorStatus.FAILED)
            self._status = BehaviorStatus.RUNNING
            self._elapsed += dt_s
            if (self.max_duration_s is not None
                    and self._elapsed >= self.max_duration_s):
                self._status = BehaviorStatus.TIMED_OUT
                return True
        done = self.update(dt_s)
        if done:
            with self._lock:
                if self._status == BehaviorStatus.RUNNING:
                    self._status = BehaviorStatus.COMPLETED
        return done

    def mark_failed(self) -> None:
        with self._lock:
            self._status = BehaviorStatus.FAILED

    # -------------------------------------------------------------- readonly
    @property
    def status(self) -> BehaviorStatus:
        with self._lock:
            return self._status

    @property
    def elapsed_s(self) -> float:
        with self._lock:
            return self._elapsed

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.behavior_type.name} {self.status.name}>"
