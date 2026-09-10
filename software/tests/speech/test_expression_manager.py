import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from speech.expression_manager import ExpressionManager
from speech.speech_config import ExpressionConfig
from speech.tests._helpers import collect

class TestExpression(unittest.TestCase):
    def test_sets_expression_and_sends_face_command(self):
        bus = EventBus(); seen = collect(bus)
        em = ExpressionManager(bus, ExpressionConfig())
        em.set_expression("HAPPY")
        types = [t for t, _ in seen]
        self.assertIn(RobotEvent.EXPRESSION_CHANGED, types)
        # face command uses the same EMOTION_CHANGED convention as Behavior layer
        face = [d for t, d in seen if t == RobotEvent.EMOTION_CHANGED]
        self.assertEqual(face[0]["emotion"], "HAPPY")

    def test_expression_held_stable(self):
        bus = EventBus(); seen = collect(bus)
        em = ExpressionManager(bus, ExpressionConfig(hold_expression=True))
        em.set_expression("HAPPY")
        em.set_expression("HAPPY")   # same -> not re-emitted
        changes = [1 for t, _ in seen if t == RobotEvent.EXPRESSION_CHANGED]
        self.assertEqual(len(changes), 1)            # stable, no churn

    def test_different_expression_updates(self):
        bus = EventBus(); seen = collect(bus)
        em = ExpressionManager(bus, ExpressionConfig())
        em.set_expression("HAPPY")
        em.set_expression("SAD")
        changes = [d for t, d in seen if t == RobotEvent.EXPRESSION_CHANGED]
        self.assertEqual(len(changes), 2)

    def test_reset_to_normal(self):
        bus = EventBus(); seen = collect(bus)
        em = ExpressionManager(bus, ExpressionConfig())
        em.set_expression("EXCITED")
        em.reset()
        self.assertEqual(em.current, "NORMAL")

if __name__ == "__main__":
    unittest.main()
