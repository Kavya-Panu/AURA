"""
core/state_machine.py
=====================
Reusable, thread-safe finite state machine plus the default AURA transition
map.

* Transitions are validated against an allow-list - illegal moves raise
  :class:`StateTransitionError` instead of silently corrupting robot state.
* Per-state entry/exit callbacks.
* Bounded history of transitions for debugging.
* Optionally publishes ``STATE_CHANGED`` on the EventBus so every module can
  react to state changes without coupling to the machine.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from core.constants import RobotEvent, RobotState
from core.event_bus import EventBus
from core.exceptions import StateTransitionError
from core.logger import get_logger

log = get_logger("state_machine")

StateCallback = Callable[[RobotState, RobotState], None]  # (from, to)


@dataclass(frozen=True)
class TransitionRecord:
    """One entry in the machine's history."""
    from_state: RobotState
    to_state: RobotState
    reason: str
    timestamp: float


# Default allow-list for AURA. FOCUS <-> LISTENING lets the user ask a
# question mid-session; ANSWERING returns to FOCUS when a session is active.
AURA_TRANSITIONS: dict[RobotState, set[RobotState]] = {
    RobotState.BOOTING:   {RobotState.IDLE, RobotState.SHUTDOWN},
    RobotState.IDLE:      {RobotState.LISTENING, RobotState.FOCUS,
                           RobotState.SEARCHING, RobotState.SLEEPING,
                           RobotState.SHUTDOWN},
    RobotState.LISTENING: {RobotState.THINKING, RobotState.IDLE,
                           RobotState.FOCUS, RobotState.SHUTDOWN},
    RobotState.THINKING:  {RobotState.ANSWERING, RobotState.IDLE,
                           RobotState.SHUTDOWN},
    RobotState.ANSWERING: {RobotState.IDLE, RobotState.LISTENING,
                           RobotState.FOCUS, RobotState.SHUTDOWN},
    RobotState.FOCUS:     {RobotState.BREAK, RobotState.LISTENING,
                           RobotState.IDLE, RobotState.SHUTDOWN},
    RobotState.BREAK:     {RobotState.FOCUS, RobotState.IDLE,
                           RobotState.SHUTDOWN},
    RobotState.SEARCHING: {RobotState.IDLE, RobotState.SHUTDOWN},
    RobotState.SLEEPING:  {RobotState.IDLE, RobotState.SHUTDOWN},
    RobotState.SHUTDOWN:  set(),
}


class StateMachine:
    """Generic validated FSM. Instantiate with any transition map; use
    :func:`build_aura_state_machine` for the robot's default one."""

    def __init__(self,
                 initial: RobotState,
                 transitions: dict[RobotState, set[RobotState]],
                 event_bus: EventBus | None = None,
                 history_size: int = 50,
                 name: str = "aura-fsm") -> None:
        self._lock = threading.RLock()
        self._state = initial
        self._transitions = {s: set(t) for s, t in transitions.items()}
        self._bus = event_bus
        self._name = name
        self._history: deque[TransitionRecord] = deque(maxlen=history_size)
        self._on_enter: dict[RobotState, list[StateCallback]] = {}
        self._on_exit: dict[RobotState, list[StateCallback]] = {}

    # ------------------------------------------------------------ inspection
    @property
    def state(self) -> RobotState:
        with self._lock:
            return self._state

    @property
    def history(self) -> list[TransitionRecord]:
        with self._lock:
            return list(self._history)

    def can_transition(self, to_state: RobotState) -> bool:
        with self._lock:
            return to_state in self._transitions.get(self._state, set())

    # ------------------------------------------------------------- callbacks
    def on_enter(self, state: RobotState, callback: StateCallback) -> None:
        """Run ``callback(from, to)`` whenever ``state`` is entered."""
        self._on_enter.setdefault(state, []).append(callback)

    def on_exit(self, state: RobotState, callback: StateCallback) -> None:
        """Run ``callback(from, to)`` whenever ``state`` is left."""
        self._on_exit.setdefault(state, []).append(callback)

    # ------------------------------------------------------------ transition
    def transition(self, to_state: RobotState, reason: str = "") -> None:
        """Move to ``to_state``. Raises StateTransitionError if not allowed.

        Callback order: exit callbacks of the old state, then enter callbacks
        of the new state, then a STATE_CHANGED event on the bus (if attached).
        Callback exceptions are logged but never abort the transition - the
        machine's state must stay consistent.
        """
        with self._lock:
            from_state = self._state
            if to_state not in self._transitions.get(from_state, set()):
                raise StateTransitionError(
                    "Illegal transition",
                    {"from": from_state.name, "to": to_state.name,
                     "machine": self._name})
            self._state = to_state
            self._history.append(TransitionRecord(
                from_state, to_state, reason, time.monotonic()))

        log.info("%s: %s -> %s%s", self._name, from_state.name, to_state.name,
                 f" ({reason})" if reason else "")

        self._fire(self._on_exit.get(from_state, []), from_state, to_state)
        self._fire(self._on_enter.get(to_state, []), from_state, to_state)

        if self._bus is not None:
            self._bus.emit(RobotEvent.STATE_CHANGED,
                           {"from": from_state.name, "to": to_state.name,
                            "reason": reason},
                           source=self._name)

    def add_transition(self, from_state: RobotState,
                       to_state: RobotState) -> None:
        """Extend the allow-list at runtime (e.g. when a future module adds
        a new state)."""
        with self._lock:
            self._transitions.setdefault(from_state, set()).add(to_state)

    # -------------------------------------------------------------- internal
    @staticmethod
    def _fire(callbacks: list[StateCallback],
              from_state: RobotState, to_state: RobotState) -> None:
        for cb in callbacks:
            try:
                cb(from_state, to_state)
            except Exception:      # noqa: BLE001 - keep the FSM consistent
                log.exception("state callback failed (%s -> %s)",
                              from_state.name, to_state.name)


def build_aura_state_machine(event_bus: EventBus | None = None) -> StateMachine:
    """The robot's default machine, starting in BOOTING."""
    return StateMachine(RobotState.BOOTING, AURA_TRANSITIONS, event_bus)
