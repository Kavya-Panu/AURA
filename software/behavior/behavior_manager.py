"""
behavior/behavior_manager.py
============================
AURA's decision core. It is the only thing that turns perception into intent.

Responsibilities (all implemented here):
* subscribe to core events, translate them into behavior requests
* choose the active behavior by priority
* preempt / queue / replace / reject per the incoming behavior's policy
* keep a resume STACK so a preempted behavior continues after its interrupter
* enforce per-behavior timeouts / max duration
* drive the active behavior's lifecycle on a ticked update loop
* request state transitions and emotions ONLY through the state machine / bus
  (never touches hardware, never mutates state fields directly)

Threading: perception events arrive on foreign threads (camera/voice). They are
recorded and turned into requests under a lock; the actual behavior stepping
happens on the manager's own tick thread, so behaviors run single-threaded and
stay simple while the manager stays thread-safe at its boundary.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from core.constants import Emotion, RobotEvent, RobotState
from core.event_bus import Event, EventBus
from core.logger import get_logger
from core.state_machine import StateMachine
from core.exceptions import StateTransitionError

from .behavior_base import Behavior
from .behavior_context import BehaviorContext
from .behavior_events import EVENT_TO_TRIGGER, BehaviorTrigger
from .behavior_registry import BehaviorRegistry, registry as default_registry
from .behavior_types import (
    BehaviorStatus,
    BehaviorType,
    InterruptPolicy,
    Priority,
)

log = get_logger("behavior.manager")

_DEFAULT_TICK_S = 0.05    # 20 Hz decision loop


# Which behavior each trigger requests. Data, not if/else - extend freely.
TRIGGER_BEHAVIOR: dict[BehaviorTrigger, BehaviorType] = {
    BehaviorTrigger.WAKE_WORD:         BehaviorType.LISTENING,
    BehaviorTrigger.USER_GREETING:     BehaviorType.GREETING,
    BehaviorTrigger.QUESTION_RECEIVED: BehaviorType.THINKING,
    BehaviorTrigger.ANSWER_READY:      BehaviorType.ANSWERING,
    BehaviorTrigger.FOCUS_STARTED:     BehaviorType.FOCUS,
    BehaviorTrigger.FOCUS_FINISHED:    BehaviorType.CELEBRATION,
    BehaviorTrigger.PHONE_DETECTED:    BehaviorType.WARNING,
    BehaviorTrigger.PERSON_FOUND:      BehaviorType.GREETING,
    BehaviorTrigger.PERSON_LOST:       BehaviorType.IDLE,
    BehaviorTrigger.BREAK_STARTED:     BehaviorType.BREAK,
    BehaviorTrigger.BATTERY_LOW:       BehaviorType.LOW_BATTERY,
    BehaviorTrigger.CAMERA_ERROR:      BehaviorType.ERROR,
    BehaviorTrigger.VOICE_ERROR:       BehaviorType.ERROR,
}

# Which behavior each robot state maps to when the manager needs a state->state
# request from a behavior (behaviors call actions.request_state()).
BEHAVIOR_STATE: dict[BehaviorType, RobotState] = {
    BehaviorType.IDLE:        RobotState.IDLE,
    BehaviorType.LISTENING:   RobotState.LISTENING,
    BehaviorType.THINKING:    RobotState.THINKING,
    BehaviorType.ANSWERING:   RobotState.ANSWERING,
    BehaviorType.FOCUS:       RobotState.FOCUS,
    BehaviorType.BOOK_MODE:   RobotState.FOCUS,
    BehaviorType.BREAK:       RobotState.BREAK,
    BehaviorType.SEARCHING:   RobotState.SEARCHING,
    BehaviorType.SLEEP:       RobotState.SLEEPING,
}


@dataclass
class _Active:
    """Bookkeeping for the currently running behavior."""
    behavior: Behavior
    priority: Priority


class BehaviorManager:
    """The perception->action decision layer. Plugs into core Bus + FSM."""

    def __init__(self,
                 event_bus: EventBus,
                 state_machine: StateMachine,
                 context: BehaviorContext,
                 registry: BehaviorRegistry | None = None,
                 tick_interval_s: float = _DEFAULT_TICK_S) -> None:
        self._bus = event_bus
        self._sm = state_machine
        self._ctx = context
        self._registry = registry or default_registry
        self._tick_s = tick_interval_s

        self._lock = threading.RLock()
        self._active: _Active | None = None
        self._resume_stack: list[_Active] = []      # preempted, awaiting resume
        self._queue: list[tuple[Priority, BehaviorType]] = []
        self._sub_ids: list[int] = []
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    # =====================================================================
    #  BehaviorActions facade (what behaviors are allowed to do)
    # =====================================================================
    def request_emotion(self, emotion: Emotion) -> None:
        """Behaviors ask for an emotion; the Emotion Manager (future) listens."""
        self._ctx.update(emotion=emotion)
        self._bus.emit(RobotEvent.EMOTION_CHANGED, {"emotion": emotion.name},
                       source="behavior")

    def request_state(self, state: RobotState, reason: str = "") -> None:
        """Behaviors REQUEST a transition; the FSM validates it. Illegal
        requests are logged and dropped - never crash the manager."""
        try:
            if self._sm.can_transition(state):
                self._sm.transition(state, reason=reason or "behavior")
                self._ctx.set_state(state)
            else:
                log.debug("state request %s rejected from %s",
                          state.name, self._sm.state.name)
        except StateTransitionError:
            log.exception("illegal state request %s", state.name)

    def request_speech(self, text: str) -> None:
        """Behaviors ask to speak; the Speech Manager (future) listens."""
        self._bus.emit(RobotEvent.SPEECH_STARTED, {"text": text},
                       source="behavior")

    def emit(self, event_name: str, **data: object) -> None:
        """Generic passthrough for behavior-published events."""
        try:
            event = RobotEvent[event_name]
        except KeyError:
            log.warning("behavior emitted unknown event '%s'", event_name)
            return
        self._bus.emit(event, dict(data), source="behavior")

    def snapshot(self):
        """Let behaviors read the current world model during update()."""
        return self._ctx.snapshot()

    # =====================================================================
    #  Lifecycle (start/stop the decision loop + bus wiring)
    # =====================================================================
    def attach(self) -> None:
        """Subscribe to triggers and establish a baseline IDLE behavior, WITHOUT
        starting the tick thread. Tests drive ticks manually via tick_once()."""
        if self._sub_ids:
            return
        for event_type in EVENT_TO_TRIGGER:
            sid = self._bus.subscribe(event_type, self._on_event, priority=50)
            self._sub_ids.append(sid)
        self.request_behavior(BehaviorType.IDLE, source="startup")
        log.info("BehaviorManager attached (%d triggers)", len(self._sub_ids))

    def start(self) -> None:
        """attach() plus the real-time tick loop for production use."""
        if self._running.is_set():
            return
        self.attach()
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="behavior-mgr",
                                        daemon=True)
        self._thread.start()
        log.info("BehaviorManager loop running (%.0f Hz)", 1.0 / self._tick_s)

    def stop(self) -> None:
        """Unsubscribe, stop the loop (if running) and exit the active behavior.
        Safe to call after either attach() or start(), and safe to call twice."""
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        for sid in self._sub_ids:
            self._bus.unsubscribe(sid)
        self._sub_ids.clear()
        with self._lock:
            if self._active is not None:
                self._safe(self._active.behavior.exit)
                self._active = None
            self._resume_stack.clear()
            self._queue.clear()
        log.info("BehaviorManager stopped")

    # =====================================================================
    #  Event handling -> behavior requests
    # =====================================================================
    def _on_event(self, event: Event) -> None:
        """Bus callback (runs on the publisher's thread). Translate the event
        into a behavior request; all heavy lifting is guarded by the lock."""
        trigger = EVENT_TO_TRIGGER.get(event.type)
        if trigger is None:
            return
        # Update context from well-known payloads.
        self._apply_event_to_context(trigger, event)
        behavior_type = TRIGGER_BEHAVIOR.get(trigger)
        if behavior_type is not None:
            self.request_behavior(behavior_type, source=event.type.name)

    def _apply_event_to_context(self, trigger: BehaviorTrigger,
                                event: Event) -> None:
        if trigger == BehaviorTrigger.PHONE_DETECTED:
            self._ctx.update(phone_detected=True)
        elif trigger == BehaviorTrigger.PHONE_REMOVED:
            self._ctx.update(phone_detected=False)
        elif trigger == BehaviorTrigger.PERSON_FOUND:
            self._ctx.update(person_present=True)
        elif trigger == BehaviorTrigger.PERSON_LOST:
            self._ctx.update(person_present=False)
        elif trigger == BehaviorTrigger.FOCUS_STARTED:
            self._ctx.update(focus_active=True)
        elif trigger in (BehaviorTrigger.FOCUS_FINISHED,):
            self._ctx.update(focus_active=False)
        elif trigger == BehaviorTrigger.BATTERY_LOW:
            self._ctx.update(battery_level=event.data.get("level", 0.1))

    # =====================================================================
    #  Behavior arbitration (priority / preempt / queue / replace / reject)
    # =====================================================================
    def request_behavior(self, behavior_type: BehaviorType,
                         source: str = "manual") -> bool:
        """Ask to run ``behavior_type``. Returns True if it became active or
        was queued, False if rejected."""
        if not self._registry.is_registered(behavior_type):
            log.warning("no behavior registered for %s (request from %s)",
                        behavior_type.name, source)
            return False

        candidate = self._registry.create(behavior_type, self)
        snap = self._ctx.snapshot()
        if not candidate.can_run(snap):
            log.debug("%s.can_run() == False; request from %s ignored",
                      behavior_type.name, source)
            return False

        new_prio = candidate.priority()
        with self._lock:
            current = self._active
            if current is None:
                self._activate(candidate, new_prio)
                return True

            if new_prio > current.priority:
                return self._preempt(current, candidate, new_prio)

            # Same or lower priority -> obey the CURRENT behavior's stance via
            # the candidate's declared policy.
            policy = candidate.interrupt_policy
            if policy == InterruptPolicy.REPLACE and new_prio == current.priority:
                self._cancel_current()
                self._activate(candidate, new_prio)
                return True
            if policy == InterruptPolicy.QUEUE:
                self._queue.append((new_prio, behavior_type))
                self._queue.sort(key=lambda p: -int(p[0]))
                log.debug("queued %s (prio %s); queue=%d",
                          behavior_type.name, new_prio.name, len(self._queue))
                return True
            log.debug("rejected %s (prio %s <= current %s)",
                      behavior_type.name, new_prio.name, current.priority.name)
            return False

    def _preempt(self, current: _Active, candidate: Behavior,
                 new_prio: Priority) -> bool:
        """Higher-priority candidate displaces the current behavior."""
        policy = candidate.interrupt_policy
        if policy == InterruptPolicy.REPLACE:
            self._cancel_current()
        elif current.priority <= Priority.BACKGROUND:
            # The fallback (IDLE) is never parked - it is regenerated as the
            # resting behavior, so just exit it cleanly.
            self._safe(current.behavior.cancel)
            self._safe(current.behavior.exit)
            self._active = None
        else:   # PREEMPT (default): pause + push a REAL task for later resume
            self._safe(current.behavior.interrupt)
            self._resume_stack.append(current)
            log.debug("preempted %s -> resume stack (depth %d)",
                      current.behavior.behavior_type.name,
                      len(self._resume_stack))
            self._active = None
        self._activate(candidate, new_prio)
        return True

    def _activate(self, behavior: Behavior, prio: Priority) -> None:
        """Make ``behavior`` the active one and run enter()+execute()."""
        self._active = _Active(behavior, prio)
        self._ctx.set_current_behavior(behavior.behavior_type, prio)
        log.info("activate %s (prio %s)",
                 behavior.behavior_type.name, prio.name)
        self._safe(behavior.enter)
        # Behaviors may request their matching state on enter.
        target_state = BEHAVIOR_STATE.get(behavior.behavior_type)
        if target_state is not None:
            self.request_state(target_state,
                               reason=behavior.behavior_type.name)
        self._safe(behavior.execute)

    def _cancel_current(self) -> None:
        if self._active is not None:
            self._safe(self._active.behavior.cancel)
            self._safe(self._active.behavior.exit)
            self._active = None

    def _finish_current(self) -> None:
        """Active behavior ended normally: exit it, then resume or dequeue."""
        if self._active is not None:
            self._safe(self._active.behavior.exit)
            self._active = None
        # 1) resume a preempted behavior if any.
        if self._resume_stack:
            resumed = self._resume_stack.pop()
            if resumed.behavior.status != BehaviorStatus.CANCELLED:
                self._active = resumed
                self._ctx.set_current_behavior(
                    resumed.behavior.behavior_type, resumed.priority)
                log.info("resume %s", resumed.behavior.behavior_type.name)
                self._safe(resumed.behavior.resume)
                return
        # 2) otherwise start the highest-priority queued behavior.
        if self._queue:
            _, behavior_type = self._queue.pop(0)
            behavior = self._registry.create(behavior_type, self)
            if behavior.can_run(self._ctx.snapshot()):
                self._activate(behavior, behavior.priority())
                return
        # 3) nothing pending -> fall back to IDLE.
        if self._registry.is_registered(BehaviorType.IDLE):
            idle = self._registry.create(BehaviorType.IDLE, self)
            self._activate(idle, idle.priority())

    # =====================================================================
    #  Tick loop
    # =====================================================================
    def _loop(self) -> None:
        import time
        last = time.monotonic()
        while self._running.is_set():
            time.sleep(self._tick_s)
            now = time.monotonic()
            dt = now - last
            last = now
            self._tick(dt)

    def _tick(self, dt_s: float) -> None:
        with self._lock:
            active = self._active
            if active is None:
                self._finish_current()   # will fall back to IDLE
                return
            try:
                done = active.behavior.tick(dt_s)
            except Exception:            # noqa: BLE001 - contain behavior bugs
                log.exception("behavior %s crashed in tick",
                              active.behavior.behavior_type.name)
                active.behavior.mark_failed()
                done = True
            if done:
                log.debug("%s finished (%s)",
                          active.behavior.behavior_type.name,
                          active.behavior.status.name)
                self._finish_current()

    # =====================================================================
    #  Introspection (for tests / debugging / a future dashboard)
    # =====================================================================
    @property
    def current_behavior(self) -> BehaviorType | None:
        with self._lock:
            return self._active.behavior.behavior_type if self._active else None

    @property
    def current(self) -> Behavior | None:
        with self._lock:
            return self._active.behavior if self._active else None

    @property
    def resume_depth(self) -> int:
        with self._lock:
            return len(self._resume_stack)

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def tick_once(self, dt_s: float) -> None:
        """Manually advance one tick (used by tests to avoid timing races)."""
        self._tick(dt_s)

    # ------------------------------------------------------------- internal
    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception:        # noqa: BLE001
            log.exception("behavior lifecycle hook failed: %s", getattr(fn, "__name__", fn))
