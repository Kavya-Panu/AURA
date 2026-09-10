"""Tests for core.event_bus."""
import threading
import unittest

from core.constants import RobotEvent
from core.event_bus import Event, EventBus


class TestEventBus(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        got = []
        self.bus.subscribe(RobotEvent.WAKE_WORD, got.append)
        n = self.bus.emit(RobotEvent.WAKE_WORD, {"word": "aura"}, source="test")
        self.assertEqual(n, 1)
        self.assertEqual(got[0].data["word"], "aura")

    def test_only_matching_type_delivered(self):
        got = []
        self.bus.subscribe(RobotEvent.FACE_FOUND, got.append)
        self.bus.emit(RobotEvent.FACE_LOST)
        self.assertEqual(got, [])

    def test_priority_order(self):
        order = []
        self.bus.subscribe(RobotEvent.PHONE_DETECTED, lambda e: order.append("low"), priority=0)
        self.bus.subscribe(RobotEvent.PHONE_DETECTED, lambda e: order.append("high"), priority=10)
        self.bus.emit(RobotEvent.PHONE_DETECTED)
        self.assertEqual(order, ["high", "low"])

    def test_unsubscribe(self):
        got = []
        sid = self.bus.subscribe(RobotEvent.WAKE_WORD, got.append)
        self.assertTrue(self.bus.unsubscribe(sid))
        self.bus.emit(RobotEvent.WAKE_WORD)
        self.assertEqual(got, [])
        self.assertFalse(self.bus.unsubscribe(sid))  # already gone

    def test_wildcard_receives_everything(self):
        got = []
        self.bus.subscribe_all(got.append)
        self.bus.emit(RobotEvent.FACE_FOUND)
        self.bus.emit(RobotEvent.BATTERY_LOW)
        self.assertEqual([e.type for e in got],
                         [RobotEvent.FACE_FOUND, RobotEvent.BATTERY_LOW])

    def test_handler_exception_does_not_break_bus(self):
        got = []
        def bad(_): raise RuntimeError("boom")
        self.bus.subscribe(RobotEvent.WAKE_WORD, bad, priority=10)
        self.bus.subscribe(RobotEvent.WAKE_WORD, got.append)
        n = self.bus.emit(RobotEvent.WAKE_WORD)
        self.assertEqual(n, 1)             # only the good handler counted
        self.assertEqual(len(got), 1)      # and it still ran

    def test_async_delivery_and_priority(self):
        got = []
        done = threading.Event()
        def handler(e):
            got.append(e.data["i"])
            if len(got) == 3:
                done.set()
        self.bus.subscribe(RobotEvent.LLM_RESPONSE, handler)
        # enqueue BEFORE starting so priority ordering is observable
        self.bus.publish_async(Event(RobotEvent.LLM_RESPONSE, {"i": 1}, priority=0))
        self.bus.publish_async(Event(RobotEvent.LLM_RESPONSE, {"i": 2}, priority=5))
        self.bus.publish_async(Event(RobotEvent.LLM_RESPONSE, {"i": 3}, priority=0))
        self.bus.start()
        self.assertTrue(done.wait(2.0))
        self.bus.stop()
        self.assertEqual(got[0], 2)          # highest priority first
        self.assertEqual(sorted(got), [1, 2, 3])

    def test_thread_safety_parallel_publish(self):
        count = []
        lock = threading.Lock()
        def handler(_):
            with lock:
                count.append(1)
        self.bus.subscribe(RobotEvent.TIMER_EXPIRED, handler)
        threads = [threading.Thread(
            target=lambda: [self.bus.emit(RobotEvent.TIMER_EXPIRED) for _ in range(50)])
            for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(count), 8 * 50)


if __name__ == "__main__":
    unittest.main()
