"""
Behavior System tests: switching, priority preemption, interruption + resume,
queueing, timeout, cancellation, and full event-driven flows.

Uses attach() + tick_once() so timing is deterministic (no background thread).
"""
import unittest

import behavior.behaviors  # noqa: F401  (registers all behaviors)
from core.constants import Emotion, RobotEvent, RobotState
from core.event_bus import EventBus
from core.state_machine import build_aura_state_machine

from behavior.behavior_context import BehaviorContext
from behavior.behavior_manager import BehaviorManager
from behavior.behavior_registry import BehaviorRegistry, registry as default_registry
from behavior.behavior_types import BehaviorType, InterruptPolicy, Priority
from behavior.behavior_base import Behavior


def make_manager():
    bus = EventBus()
    sm = build_aura_state_machine(bus)
    sm.transition(RobotState.IDLE, reason="test setup")   # leave BOOTING
    ctx = BehaviorContext(RobotState.IDLE)
    mgr = BehaviorManager(bus, sm, ctx, registry=default_registry)
    mgr.attach()
    return bus, sm, ctx, mgr


class TestSwitching(unittest.TestCase):
    def test_starts_in_idle(self):
        _, _, _, mgr = make_manager()
        self.assertEqual(mgr.current_behavior, BehaviorType.IDLE)

    def test_request_switches_behavior(self):
        _, _, _, mgr = make_manager()
        self.assertTrue(mgr.request_behavior(BehaviorType.GREETING))
        self.assertEqual(mgr.current_behavior, BehaviorType.GREETING)

    def test_greeting_completes_and_returns_to_idle(self):
        _, _, _, mgr = make_manager()
        mgr.request_behavior(BehaviorType.GREETING)
        for _ in range(50):                 # 50 * 0.05 = 2.5s > greeting 2.0s
            mgr.tick_once(0.05)
            if mgr.current_behavior == BehaviorType.IDLE:
                break
        self.assertEqual(mgr.current_behavior, BehaviorType.IDLE)


class TestPriorityAndPreemption(unittest.TestCase):
    def test_higher_priority_preempts(self):
        _, _, ctx, mgr = make_manager()
        ctx.update(focus_active=True)
        mgr.request_behavior(BehaviorType.FOCUS)
        self.assertEqual(mgr.current_behavior, BehaviorType.FOCUS)
        ctx.update(phone_detected=True)
        mgr.request_behavior(BehaviorType.WARNING)      # HIGH > NORMAL
        self.assertEqual(mgr.current_behavior, BehaviorType.WARNING)
        self.assertEqual(mgr.resume_depth, 1)           # focus parked

    def test_lower_priority_rejected(self):
        _, _, ctx, mgr = make_manager()
        ctx.update(focus_active=True)
        mgr.request_behavior(BehaviorType.FOCUS)
        # GREETING is NORMAL == FOCUS NORMAL and default policy PREEMPT -> not >,
        # not REPLACE, not QUEUE -> rejected.
        self.assertFalse(mgr.request_behavior(BehaviorType.GREETING))
        self.assertEqual(mgr.current_behavior, BehaviorType.FOCUS)

    def test_system_priority_replaces(self):
        _, _, _, mgr = make_manager()
        mgr.request_behavior(BehaviorType.GREETING)
        mgr.request_behavior(BehaviorType.SLEEP)        # SYSTEM, REPLACE
        self.assertEqual(mgr.current_behavior, BehaviorType.SLEEP)
        self.assertEqual(mgr.resume_depth, 0)           # greeting NOT parked


class TestInterruptResume(unittest.TestCase):
    def test_focus_phone_warning_resume_flow(self):
        _, _, ctx, mgr = make_manager()
        ctx.update(focus_active=True)
        mgr.request_behavior(BehaviorType.FOCUS)

        # Phone appears -> warning preempts focus.
        ctx.update(phone_detected=True)
        mgr.request_behavior(BehaviorType.WARNING)
        self.assertEqual(mgr.current_behavior, BehaviorType.WARNING)

        # Phone removed -> warning finishes -> focus resumes.
        ctx.update(phone_detected=False)
        for _ in range(5):
            mgr.tick_once(0.05)
            if mgr.current_behavior == BehaviorType.FOCUS:
                break
        self.assertEqual(mgr.current_behavior, BehaviorType.FOCUS)
        self.assertEqual(mgr.resume_depth, 0)


class TestQueue(unittest.TestCase):
    def test_queue_policy_runs_after_current(self):
        _, _, _, mgr = make_manager()

        # A queueing behavior at equal priority waits its turn.
        reg = default_registry

        @reg.register(BehaviorType.WAKE)   # reuse an unused type as a test slot
        class QueuedBehavior(Behavior):
            interrupt_policy = InterruptPolicy.QUEUE
            def priority(self): return Priority.NORMAL
            def update(self, dt): return self.elapsed_s >= 0.05

        try:
            mgr.request_behavior(BehaviorType.GREETING)
            self.assertTrue(mgr.request_behavior(BehaviorType.WAKE))  # queued
            self.assertEqual(mgr.queue_size, 1)
            self.assertEqual(mgr.current_behavior, BehaviorType.GREETING)
            for _ in range(60):
                mgr.tick_once(0.05)
                if mgr.current_behavior == BehaviorType.WAKE:
                    break
            self.assertEqual(mgr.current_behavior, BehaviorType.WAKE)
        finally:
            reg._classes.pop(BehaviorType.WAKE, None)


class TestTimeout(unittest.TestCase):
    def test_max_duration_times_out(self):
        _, _, ctx, mgr = make_manager()
        ctx.update(phone_detected=True)          # keeps WARNING from self-ending
        mgr.request_behavior(BehaviorType.WARNING)
        current = mgr.current
        self.assertEqual(mgr.current_behavior, BehaviorType.WARNING)
        # WARNING max_duration_s = 30 -> tick past it.
        for _ in range(int(30 / 0.5) + 2):
            mgr.tick_once(0.5)
            if mgr.current_behavior != BehaviorType.WARNING:
                break
        self.assertNotEqual(mgr.current_behavior, BehaviorType.WARNING)


class TestCancellation(unittest.TestCase):
    def test_stop_exits_active(self):
        _, _, _, mgr = make_manager()
        mgr.request_behavior(BehaviorType.GREETING)
        mgr.stop()
        self.assertIsNone(mgr.current)


class TestEventDriven(unittest.TestCase):
    def test_wake_word_event_triggers_listening(self):
        bus, _, _, mgr = make_manager()
        bus.emit(RobotEvent.WAKE_WORD, source="voice")
        self.assertEqual(mgr.current_behavior, BehaviorType.LISTENING)

    def test_phone_event_triggers_warning_over_focus(self):
        bus, _, ctx, mgr = make_manager()
        ctx.update(focus_active=True)
        bus.emit(RobotEvent.FOCUS_STARTED, source="focus")
        self.assertEqual(mgr.current_behavior, BehaviorType.FOCUS)
        bus.emit(RobotEvent.PHONE_DETECTED, {"seconds": 61}, source="vision")
        self.assertEqual(mgr.current_behavior, BehaviorType.WARNING)

    def test_state_transition_requested_not_mutated(self):
        bus, sm, _, mgr = make_manager()
        bus.emit(RobotEvent.WAKE_WORD, source="voice")
        # Manager requested LISTENING via the FSM (valid IDLE->LISTENING).
        self.assertEqual(sm.state, RobotState.LISTENING)

    def test_emotion_requests_go_on_bus(self):
        bus, _, _, mgr = make_manager()
        got = []
        bus.subscribe(RobotEvent.EMOTION_CHANGED, lambda e: got.append(e.data["emotion"]))
        bus.emit(RobotEvent.WAKE_WORD, source="voice")
        self.assertIn(Emotion.LISTENING.name, got)


class TestRegistry(unittest.TestCase):
    def test_duplicate_registration_raises(self):
        reg = BehaviorRegistry()
        @reg.register(BehaviorType.IDLE)
        class A(Behavior):
            def update(self, dt): return True
        with self.assertRaises(ValueError):
            @reg.register(BehaviorType.IDLE)
            class B(Behavior):
                def update(self, dt): return True

    def test_create_unregistered_raises(self):
        reg = BehaviorRegistry()
        with self.assertRaises(KeyError):
            reg.create(BehaviorType.FOCUS, actions=None)


if __name__ == "__main__":
    unittest.main()
