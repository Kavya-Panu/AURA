import threading
import unittest
from speech.speech_queue import SpeechQueue

class TestSpeechQueue(unittest.TestCase):
    def test_fifo_same_priority(self):
        q = SpeechQueue()
        q.put("a"); q.put("b"); q.put("c")
        self.assertEqual([q.get().text for _ in range(3)], ["a", "b", "c"])

    def test_priority_jumps_ahead(self):
        q = SpeechQueue()
        q.put("normal", priority=100)
        q.put("urgent", priority=0)
        self.assertEqual(q.get().text, "urgent")   # higher priority first
        self.assertEqual(q.get().text, "normal")

    def test_full_queue_rejects(self):
        q = SpeechQueue(maxsize=2)
        self.assertTrue(q.put("1"))
        self.assertTrue(q.put("2"))
        self.assertFalse(q.put("3"))               # full

    def test_clear_cancels_all(self):
        q = SpeechQueue()
        q.put("a"); q.put("b")
        self.assertEqual(q.clear(), 2)
        self.assertTrue(q.is_empty)

    def test_get_timeout(self):
        q = SpeechQueue()
        self.assertIsNone(q.get(timeout=0.05))

    def test_interrupt_flag_carried(self):
        q = SpeechQueue()
        q.put("stop now", priority=0, interrupt=True)
        self.assertTrue(q.get().interrupt)

    def test_thread_safe(self):
        q = SpeechQueue(maxsize=10000)
        def worker(i):
            for j in range(200):
                q.put(f"{i}-{j}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(q), 1600)

if __name__ == "__main__":
    unittest.main()
