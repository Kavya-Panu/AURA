import threading
import time
import unittest
from hardware.command_router import (
    CommandRouter, HardwareCommand, CommandStatus)
from hardware.device_types import CommandPriority
from hardware.hardware_exceptions import CommandError

class TestCommandRouter(unittest.TestCase):
    def _wait(self, pred, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred(): return True
            time.sleep(0.004)
        return pred()

    def test_routes_and_dispatches(self):
        got = []
        r = CommandRouter(); r.start()
        r.submit(HardwareCommand("led", lambda: got.append("led")))
        self.assertTrue(self._wait(lambda: got == ["led"]))
        r.stop()

    def test_priority_order(self):
        got = []
        r = CommandRouter()      # not started: enqueue both first
        r.submit(HardwareCommand("a", lambda: got.append("normal"),
                                 CommandPriority.NORMAL))
        r.submit(HardwareCommand("b", lambda: got.append("critical"),
                                 CommandPriority.CRITICAL))
        r.start()
        self.assertTrue(self._wait(lambda: len(got) == 2))
        self.assertEqual(got[0], "critical")   # higher priority first
        r.stop()

    def test_conflict_coalescing(self):
        got = []
        r = CommandRouter()
        r.submit(HardwareCommand("servo:pan", lambda: got.append("old"),
                                 coalesce=True))
        r.submit(HardwareCommand("servo:pan", lambda: got.append("new"),
                                 coalesce=True))
        r.start()
        self.assertTrue(self._wait(lambda: got == ["new"]))  # old superseded
        r.stop()

    def test_no_coalesce_keeps_both(self):
        got = []
        r = CommandRouter()
        r.submit(HardwareCommand("face", lambda: got.append(1), coalesce=False))
        r.submit(HardwareCommand("face", lambda: got.append(2), coalesce=False))
        r.start()
        self.assertTrue(self._wait(lambda: len(got) == 2))
        r.stop()

    def test_cancel_target(self):
        got = []
        r = CommandRouter()
        r.submit(HardwareCommand("led", lambda: got.append("x")))
        cancelled = r.cancel("led")
        r.start()
        time.sleep(0.05)
        self.assertEqual(cancelled, 1)
        self.assertEqual(got, [])              # never dispatched
        r.stop()

    def test_cancel_all(self):
        r = CommandRouter()
        for i in range(5):
            r.submit(HardwareCommand(f"t{i}", lambda: None, coalesce=False))
        self.assertEqual(r.cancel_all(), 5)
        r.stop()

    def test_validation_rejects(self):
        r = CommandRouter(validator=lambda c: c.target != "bad")
        with self.assertRaises(CommandError):
            r.submit(HardwareCommand("bad", lambda: None))

    def test_queue_full(self):
        r = CommandRouter(max_queue=2)
        r.submit(HardwareCommand("a", lambda: None, coalesce=False))
        r.submit(HardwareCommand("b", lambda: None, coalesce=False))
        with self.assertRaises(CommandError):
            r.submit(HardwareCommand("c", lambda: None, coalesce=False))

    def test_thread_safe_submit(self):
        got = []
        lock = threading.Lock()
        r = CommandRouter(max_queue=10000); r.start()
        def worker(i):
            for j in range(50):
                r.submit(HardwareCommand(f"t{i}-{j}",
                                         lambda: (lock.acquire(), got.append(1),
                                                  lock.release()),
                                         coalesce=False))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(self._wait(lambda: len(got) == 300, timeout=3.0))
        r.stop()

if __name__ == "__main__":
    unittest.main()
