"""Tests for core.state_machine."""
import unittest

from core.constants import RobotEvent, RobotState
from core.event_bus import EventBus
from core.exceptions import StateTransitionError
from core.state_machine import build_aura_state_machine


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.sm = build_aura_state_machine()

    def test_initial_state(self):
        self.assertEqual(self.sm.state, RobotState.BOOTING)

    def test_valid_transition(self):
        self.sm.transition(RobotState.IDLE)
        self.assertEqual(self.sm.state, RobotState.IDLE)

    def test_invalid_transition_raises(self):
        with self.assertRaises(StateTransitionError):
            self.sm.transition(RobotState.FOCUS)   # BOOTING -> FOCUS illegal
        self.assertEqual(self.sm.state, RobotState.BOOTING)  # unchanged

    def test_can_transition(self):
        self.assertTrue(self.sm.can_transition(RobotState.IDLE))
        self.assertFalse(self.sm.can_transition(RobotState.BREAK))

    def test_enter_exit_callbacks_and_order(self):
        calls = []
        self.sm.on_exit(RobotState.BOOTING, lambda f, t: calls.append(("exit", f, t)))
        self.sm.on_enter(RobotState.IDLE, lambda f, t: calls.append(("enter", f, t)))
        self.sm.transition(RobotState.IDLE)
        self.assertEqual(calls, [("exit", RobotState.BOOTING, RobotState.IDLE),
                                 ("enter", RobotState.BOOTING, RobotState.IDLE)])

    def test_callback_exception_does_not_corrupt_state(self):
        def bad(f, t): raise RuntimeError("boom")
        self.sm.on_enter(RobotState.IDLE, bad)
        self.sm.transition(RobotState.IDLE)          # must not raise
        self.assertEqual(self.sm.state, RobotState.IDLE)

    def test_history_records(self):
        self.sm.transition(RobotState.IDLE, reason="test")
        self.sm.transition(RobotState.FOCUS)
        hist = self.sm.history
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0].reason, "test")
        self.assertEqual(hist[1].to_state, RobotState.FOCUS)

    def test_bus_integration_publishes_state_changed(self):
        bus = EventBus()
        got = []
        bus.subscribe(RobotEvent.STATE_CHANGED, got.append)
        sm = build_aura_state_machine(bus)
        sm.transition(RobotState.IDLE)
        self.assertEqual(got[0].data["to"], "IDLE")

    def test_full_focus_journey(self):
        for s in (RobotState.IDLE, RobotState.FOCUS, RobotState.LISTENING,
                  RobotState.THINKING, RobotState.ANSWERING, RobotState.FOCUS,
                  RobotState.BREAK, RobotState.FOCUS, RobotState.IDLE,
                  RobotState.SHUTDOWN):
            self.sm.transition(s)
        self.assertEqual(self.sm.state, RobotState.SHUTDOWN)
        self.assertFalse(self.sm.can_transition(RobotState.IDLE))  # terminal


if __name__ == "__main__":
    unittest.main()
