"""VoiceSystem satisfies the core Module protocol and integrates with lifecycle."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import Module
from voice.factory import build_fake_voice_system
from voice.voice_config import VoiceConfig
from voice.backends import FakeMicrophone, FakeSTT

class TestLifecycle(unittest.TestCase):
    def test_satisfies_module_protocol(self):
        bus = EventBus()
        vs = build_fake_voice_system(bus)
        self.assertIsInstance(vs, Module)

    def test_start_stop_emits_events(self):
        bus = EventBus()
        mic = FakeMicrophone(); stt = FakeSTT()
        vs = build_fake_voice_system(bus, VoiceConfig(), mic=mic, stt=stt)
        seen = []
        bus.subscribe(RobotEvent.VOICE_STARTED, lambda e: seen.append("start"))
        bus.subscribe(RobotEvent.VOICE_STOPPED, lambda e: seen.append("stop"))
        vs.initialize(); vs.start()
        self.assertTrue(vs.health_check())
        vs.stop()
        self.assertEqual(seen, ["start", "stop"])

    def test_health_false_before_start(self):
        vs = build_fake_voice_system(EventBus())
        self.assertFalse(vs.health_check())

if __name__ == "__main__":
    unittest.main()
