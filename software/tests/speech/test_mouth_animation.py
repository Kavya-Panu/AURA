import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from speech.mouth_animation import MouthAnimator, Viseme, visemes_for
from speech.speech_config import MouthConfig
from speech.tests._helpers import collect, wait_until

class TestMouth(unittest.TestCase):
    def test_visemes_open_on_vowels(self):
        seq = visemes_for("aeiou")
        self.assertTrue(all(v == Viseme.WIDE for v in seq))

    def test_visemes_close_on_space(self):
        seq = visemes_for("a a")
        self.assertEqual(seq[1], Viseme.CLOSED)

    def test_empty_text_yields_closed(self):
        self.assertEqual(visemes_for(""), [Viseme.CLOSED])

    def test_animation_emits_events(self):
        bus = EventBus(); seen = collect(bus)
        m = MouthAnimator(bus, MouthConfig(frame_interval_s=0.01))
        m.start("hello world", duration_s=0.1)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.MOUTH_ANIMATION_STOPPED for t, _ in seen)))
        types = [t for t, _ in seen]
        self.assertIn(RobotEvent.MOUTH_ANIMATION_STARTED, types)
        self.assertIn(RobotEvent.MOUTH_ANIMATION_STOPPED, types)
        # emitted mouth shapes via EMOTION_CHANGED with a "mouth" key
        mouths = [d for t, d in seen if t == RobotEvent.EMOTION_CHANGED and "mouth" in d]
        self.assertTrue(mouths)

    def test_stop_interrupts(self):
        bus = EventBus(); seen = collect(bus)
        m = MouthAnimator(bus, MouthConfig(frame_interval_s=0.01))
        m.start("a very long sentence to animate for a while", duration_s=5.0)
        m.stop()
        self.assertFalse(m.is_animating)

    def test_ends_closed(self):
        bus = EventBus(); seen = collect(bus)
        m = MouthAnimator(bus, MouthConfig(frame_interval_s=0.01))
        m.start("hi", duration_s=0.05)
        wait_until(lambda: any(t == RobotEvent.MOUTH_ANIMATION_STOPPED for t, _ in seen))
        mouth_shapes = [d["mouth"] for t, d in seen
                        if t == RobotEvent.EMOTION_CHANGED and "mouth" in d]
        self.assertEqual(mouth_shapes[-1], Viseme.CLOSED.value)

if __name__ == "__main__":
    unittest.main()
