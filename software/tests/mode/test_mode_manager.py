"""
Mode System tests: mode changes, invalid transitions, parameters, previous-mode
resume, callbacks/guards, event publishing, and thread safety.
"""
import threading
import unittest

from core.constants import RobotEvent
from core.event_bus import EventBus

from mode.mode_context import ModeContext
from mode.mode_manager import ModeManager
from mode.mode_transition import TransitionValidator
from mode.mode_types import (
    FocusParams,
    ModeType,
    TranslationParams,
)


def make_manager(initial=ModeType.NORMAL):
    bus = EventBus()
    ctx = ModeContext(initial)
    mgr = ModeManager(bus, context=ctx)
    mgr.attach()
    return bus, mgr


class TestModeChanges(unittest.TestCase):
    def test_starts_in_normal(self):
        _, mgr = make_manager()
        self.assertEqual(mgr.current_mode, ModeType.NORMAL)

    def test_normal_to_focus_allowed(self):
        _, mgr = make_manager()
        self.assertTrue(mgr.request_mode(ModeType.FOCUS))
        self.assertEqual(mgr.current_mode, ModeType.FOCUS)

    def test_normal_to_teacher_allowed(self):
        _, mgr = make_manager()
        self.assertTrue(mgr.request_mode(ModeType.TEACHER))
        self.assertEqual(mgr.current_mode, ModeType.TEACHER)

    def test_idempotent_same_mode(self):
        _, mgr = make_manager()
        self.assertTrue(mgr.request_mode(ModeType.NORMAL))   # already NORMAL
        self.assertEqual(mgr.current_mode, ModeType.NORMAL)


class TestInvalidTransitions(unittest.TestCase):
    def test_focus_to_translation_blocked(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS)
        self.assertFalse(mgr.request_mode(ModeType.TRANSLATION))  # must hub
        self.assertEqual(mgr.current_mode, ModeType.FOCUS)

    def test_focus_to_normal_to_translation(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS)
        self.assertTrue(mgr.request_mode(ModeType.NORMAL))
        self.assertTrue(mgr.request_mode(ModeType.TRANSLATION))
        self.assertEqual(mgr.current_mode, ModeType.TRANSLATION)

    def test_night_to_focus_blocked(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.NIGHT)
        self.assertFalse(mgr.request_mode(ModeType.FOCUS))   # must wake first
        self.assertTrue(mgr.request_mode(ModeType.NORMAL))   # wake
        self.assertTrue(mgr.request_mode(ModeType.FOCUS))

    def test_force_bypasses_validation(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS)
        self.assertTrue(mgr.request_mode(ModeType.TRANSLATION, force=True))
        self.assertEqual(mgr.current_mode, ModeType.TRANSLATION)

    def test_charging_reachable_from_anywhere(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS)
        self.assertTrue(mgr.request_mode(ModeType.CHARGING))  # plug in mid-focus


class TestParameters(unittest.TestCase):
    def test_default_params_applied(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS)
        params = mgr.snapshot().params
        self.assertIsInstance(params, FocusParams)
        self.assertEqual(params.duration_minutes, 120)

    def test_custom_params(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.NORMAL)
        mgr.request_mode(ModeType.TRANSLATION,
                         params=TranslationParams(source_language="English",
                                                  target_language="Japanese",
                                                  bidirectional=True))
        p = mgr.snapshot().params
        self.assertEqual(p.target_language, "Japanese")
        self.assertTrue(p.continuous)

    def test_update_params_in_place(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.QUIZ)
        mgr.update_params(score=5, questions_remaining=3)
        p = mgr.snapshot().params
        self.assertEqual(p.score, 5)
        self.assertEqual(p.questions_remaining, 3)

    def test_reentry_updates_params(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS, params=FocusParams(duration_minutes=60))
        mgr.request_mode(ModeType.FOCUS, params=FocusParams(duration_minutes=180))
        self.assertEqual(mgr.snapshot().params.duration_minutes, 180)


class TestPreviousMode(unittest.TestCase):
    def test_previous_tracked(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.FOCUS)
        mgr.request_mode(ModeType.NORMAL)
        self.assertEqual(mgr.previous_mode, ModeType.FOCUS)

    def test_resume_previous(self):
        _, mgr = make_manager()
        mgr.request_mode(ModeType.ASSISTANT)
        mgr.request_mode(ModeType.NORMAL)
        self.assertTrue(mgr.resume_previous())
        self.assertEqual(mgr.current_mode, ModeType.ASSISTANT)

    def test_resume_without_previous(self):
        _, mgr = make_manager()
        self.assertFalse(mgr.resume_previous())


class TestCallbacksAndGuards(unittest.TestCase):
    def test_enter_exit_callbacks(self):
        _, mgr = make_manager()
        calls = []
        mgr.on_exit(ModeType.NORMAL, lambda s: calls.append(("exit", s.current)))
        mgr.on_enter(ModeType.FOCUS, lambda s: calls.append(("enter", s.current)))
        mgr.request_mode(ModeType.FOCUS)
        self.assertEqual(calls, [("exit", ModeType.NORMAL),
                                 ("enter", ModeType.FOCUS)])

    def test_change_callback(self):
        _, mgr = make_manager()
        seen = []
        mgr.on_change(lambda s: seen.append(s.current))
        mgr.request_mode(ModeType.FOCUS)
        self.assertEqual(seen, [ModeType.FOCUS])

    def test_guard_vetoes_transition(self):
        _, mgr = make_manager()
        mgr.add_guard(ModeType.FOCUS, lambda f, t: False)  # always veto
        self.assertFalse(mgr.request_mode(ModeType.FOCUS))
        self.assertEqual(mgr.current_mode, ModeType.NORMAL)

    def test_callback_exception_does_not_break_transition(self):
        _, mgr = make_manager()
        def bad(s): raise RuntimeError("boom")
        mgr.on_enter(ModeType.FOCUS, bad)
        self.assertTrue(mgr.request_mode(ModeType.FOCUS))  # still succeeds
        self.assertEqual(mgr.current_mode, ModeType.FOCUS)


class TestEvents(unittest.TestCase):
    def test_lifecycle_events_published(self):
        bus, mgr = make_manager()
        seen = []
        for ev in (RobotEvent.MODE_ENTERING, RobotEvent.MODE_ENTERED,
                   RobotEvent.MODE_EXITING, RobotEvent.MODE_EXITED,
                   RobotEvent.MODE_CHANGED):
            bus.subscribe(ev, lambda e, ev=ev: seen.append(ev))
        mgr.request_mode(ModeType.FOCUS)
        for ev in (RobotEvent.MODE_EXITING, RobotEvent.MODE_ENTERING,
                   RobotEvent.MODE_EXITED, RobotEvent.MODE_ENTERED,
                   RobotEvent.MODE_CHANGED):
            self.assertIn(ev, seen)

    def test_focus_mode_started_event(self):
        bus, mgr = make_manager()
        got = []
        bus.subscribe(RobotEvent.FOCUS_MODE_STARTED,
                      lambda e: got.append(e.data))
        mgr.request_mode(ModeType.FOCUS, params=FocusParams(duration_minutes=90))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["duration_minutes"], 90)

    def test_failed_event_on_invalid(self):
        bus, mgr = make_manager()
        got = []
        bus.subscribe(RobotEvent.MODE_FAILED, lambda e: got.append(e.data))
        mgr.request_mode(ModeType.FOCUS)
        mgr.request_mode(ModeType.TRANSLATION)   # blocked
        self.assertEqual(got[0]["to"], "TRANSLATION")

    def test_mode_requested_via_bus(self):
        bus, mgr = make_manager()
        bus.emit(RobotEvent.MODE_REQUESTED, {"mode": "FOCUS"}, source="voice")
        self.assertEqual(mgr.current_mode, ModeType.FOCUS)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_requests_stay_consistent(self):
        _, mgr = make_manager()
        targets = [ModeType.FOCUS, ModeType.TEACHER, ModeType.QUIZ,
                   ModeType.NORMAL, ModeType.ASSISTANT, ModeType.HOMEWORK]

        def worker():
            for _ in range(100):
                for m in targets:
                    mgr.request_mode(m)   # many will validly fail; must not crash

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        # End state must be a real, registered mode; no corruption/exception.
        self.assertIn(mgr.current_mode, set(ModeType))


class TestTransitionValidator(unittest.TestCase):
    def test_extensible_allow(self):
        v = TransitionValidator()
        self.assertFalse(v.is_allowed(ModeType.FOCUS, ModeType.TRANSLATION))
        v.allow(ModeType.FOCUS, ModeType.TRANSLATION)
        self.assertTrue(v.is_allowed(ModeType.FOCUS, ModeType.TRANSLATION))

    def test_same_mode_not_allowed(self):
        v = TransitionValidator()
        self.assertFalse(v.is_allowed(ModeType.FOCUS, ModeType.FOCUS))


if __name__ == "__main__":
    unittest.main()
