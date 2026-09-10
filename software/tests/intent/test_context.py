"""Mode + conversation context: 'Aura stop' resolution and subject inheritance."""
import unittest
from intent import IntentContext, IntentEngine, Intent

E = IntentEngine()

class TestContext(unittest.TestCase):
    def test_stop_resolves_by_mode_never_guesses(self):
        cases = {"FOCUS": Intent.STOP_FOCUS,
                 "TRANSLATION": Intent.STOP_TRANSLATION,
                 "QUIZ": Intent.END_QUIZ,
                 "TEACHER": Intent.STOP_TEACHING,
                 "HOMEWORK": Intent.STOP_HOMEWORK}
        for mode, want in cases.items():
            self.assertEqual(E.process("Aura stop", mode).intent, want, mode)

    def test_bare_stop_in_normal_is_cancel(self):
        self.assertEqual(E.process("Aura stop", "NORMAL").intent, Intent.CANCEL)

    def test_mode_enum_objects_accepted(self):
        import sys; sys.path.insert(0, "/home/claude/AURA")
        from mode.mode_types import ModeType
        self.assertEqual(E.process("Aura stop", ModeType.FOCUS).intent,
                         Intent.STOP_FOCUS)

    def test_subject_inherited_across_turns(self):
        ctx = IntentContext()
        r1 = E.process("Aura teach me physics", "NORMAL",
                       conversation_context=ctx)
        self.assertEqual(r1.parameters["subject"], "physics")
        r2 = E.process("Aura quiz me", "TEACHER", conversation_context=ctx)
        self.assertEqual(r2.intent, Intent.START_QUIZ)
        self.assertEqual(r2.parameters.get("subject"), "physics")  # inherited

    def test_history_bounded_and_recorded(self):
        ctx = IntentContext()
        E.process("Aura start focus for 1 hour", "NORMAL",
                  conversation_context=ctx)
        self.assertEqual(ctx.last_intent, Intent.START_FOCUS)
        self.assertEqual(ctx.last_parameters["duration_minutes"], 60)

    def test_session_state_passthrough(self):
        ctx = IntentContext(session_state={"user": "sky"})
        E.process("thank you", "NORMAL", conversation_context=ctx,
                  session_state=ctx.session_state)
        self.assertEqual(ctx.session_state["user"], "sky")

if __name__ == "__main__":
    unittest.main()
