"""SpeechManager runs under the real LifecycleManager and speaks Brain answers."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from speech import SpeechManager, TTSManager, FakeTTS, AudioPlayer, FakeAudioSink
from speech.tests._helpers import instant_config, wait_until

class TestIntegration(unittest.TestCase):
    def test_lifecycle_and_brain_to_speech(self):
        bus = EventBus()
        sm_state = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm_state)
        speech = SpeechManager(bus, instant_config(),
                               TTSManager([FakeTTS("fake")]),
                               AudioPlayer(FakeAudioSink(speed=500)))
        life.register(speech)
        life.startup()
        self.assertTrue(life.health_report()["speech"])
        started = []
        bus.subscribe(RobotEvent.SPEECH_STARTED, lambda e: started.append(e.data))
        # Brain publishes an answer -> Speech speaks it
        bus.emit(RobotEvent.ANSWER_READY,
                 {"text": "Hello, I can help with that.", "success": True,
                  "mode": "ASSISTANT"}, source="brain")
        self.assertTrue(wait_until(lambda: len(started) >= 1))
        life.shutdown()

if __name__ == "__main__":
    unittest.main()
