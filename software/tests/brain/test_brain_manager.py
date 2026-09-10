"""BrainManager: fallback, timeout, retry, caching, events, bus integration, threads."""
import threading
import time
import unittest
from core.constants import RobotEvent
from core.lifecycle import Module
from brain import BrainManager, BrainConfig, MockProvider, TaskKind, KnowledgeRequest
from brain.brain_config import ProviderConfig, SelectionRules
from brain.provider_registry import GenerationRequest
from brain.brain_result import BrainResult
from brain.tests._helpers import build_brain, collect

class TestBrainManager(unittest.TestCase):
    def test_is_module(self):
        bus, brain = build_brain(start=False)
        self.assertIsInstance(brain, Module)
        brain.stop()

    def test_ask_returns_answer(self):
        bus, brain = build_brain()
        r = brain.ask("hello", mode="ASSISTANT")
        self.assertTrue(r.success)
        self.assertIn("hello", r.response)
        brain.stop()

    def test_provider_fallback_on_failure(self):
        # ollama fails -> should fall back to next in chain and still succeed
        ollama = MockProvider("ollama", is_local=True, fail=True)
        claude = MockProvider("claude")
        openai = MockProvider("openai")
        bus, brain = build_brain([ollama, claude, openai])
        seen = collect(bus)
        r = brain.ask("hi", mode="ASSISTANT")
        self.assertTrue(r.success)
        self.assertNotEqual(r.provider, "ollama")   # fell back
        self.assertIn(RobotEvent.BRAIN_COMPLETED, [t for t, _ in seen])
        brain.stop()

    def test_all_providers_fail_emits_brain_failed(self):
        bus, brain = build_brain([MockProvider("ollama", is_local=True, fail=True),
                                  MockProvider("claude", fail=True),
                                  MockProvider("openai", fail=True)])
        seen = collect(bus)
        r = brain.ask("hi")
        self.assertFalse(r.success)
        self.assertIn(RobotEvent.BRAIN_FAILED, [t for t, _ in seen])
        brain.stop()

    def test_retry_then_succeed(self):
        # provider fails the first N calls then succeeds; retries should recover
        class FlakyProvider(MockProvider):
            def __init__(self):
                super().__init__("ollama", is_local=True)
                self.attempts = 0
            def generate(self, request):
                self.attempts += 1
                if self.attempts < 2:
                    from brain.brain_exceptions import ProviderError
                    raise ProviderError("transient")
                return super().generate(request)
        cfg = BrainConfig.default()
        # give ollama retries
        for p in cfg.providers:
            if p.name == "ollama":
                p.max_retries = 3
        flaky = FlakyProvider()
        bus, brain = build_brain([flaky, MockProvider("claude")], config=cfg)
        r = brain.ask("hi", mode="ASSISTANT")
        self.assertTrue(r.success)
        self.assertEqual(r.provider, "ollama")   # recovered via retry
        self.assertGreaterEqual(flaky.attempts, 2)
        brain.stop()

    def test_timeout_falls_back(self):
        # a slow provider should time out and fall back to a fast one
        class SlowProvider(MockProvider):
            def generate(self, request):
                time.sleep(0.5)
                return super().generate(request)
        cfg = BrainConfig.default()
        cfg.request_timeout_s = 0.05
        for p in cfg.providers:      # no retries so the timeout is quick
            p.max_retries = 0
        slow = SlowProvider("ollama", is_local=True)
        fast = MockProvider("claude")
        bus, brain = build_brain([slow, fast], config=cfg)
        r = brain.ask("hi", mode="ASSISTANT", timeout_s=0.05)
        self.assertTrue(r.success)
        self.assertEqual(r.provider, "claude")   # fell back after timeout
        brain.stop()

    def test_caching_returns_cached(self):
        counter = MockProvider("ollama", is_local=True)
        bus, brain = build_brain([counter, MockProvider("claude")])
        r1 = brain.ask("same question", mode="ASSISTANT")
        calls_after_first = counter.calls
        r2 = brain.ask("same question", mode="ASSISTANT")
        self.assertEqual(counter.calls, calls_after_first)   # served from cache
        self.assertTrue(r2.metadata.get("cache_hit"))
        brain.stop()

    def test_provider_changed_event(self):
        bus, brain = build_brain()
        seen = collect(bus)
        brain.ask("hi", mode="ASSISTANT")
        self.assertIn(RobotEvent.PROVIDER_CHANGED, [t for t, _ in seen])
        brain.stop()

    def test_question_received_produces_answer_ready(self):
        bus, brain = build_brain()
        seen = collect(bus)
        bus.emit(RobotEvent.QUESTION_RECEIVED,
                 {"text": "what is python?", "mode": "ASSISTANT"}, source="intent")
        answers = [d for t, d in seen if t == RobotEvent.ANSWER_READY]
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers[0]["success"])
        brain.stop()

    def test_conversation_history_used(self):
        bus, brain = build_brain()
        brain.ask("first question", mode="ASSISTANT", session_id="s1")
        brain.ask("second question", mode="ASSISTANT", session_id="s1")
        # the second request's context should include the first turn
        msgs = brain._conversations.get("s1").messages()
        self.assertGreaterEqual(len(msgs), 3)
        brain.stop()

    def test_health_check(self):
        bus, brain = build_brain(start=False)
        brain.start()
        self.assertTrue(brain.health_check())
        brain.stop()
        self.assertFalse(brain.health_check())

    def test_thread_safety_concurrent_requests(self):
        bus, brain = build_brain()
        results = []
        lock = threading.Lock()
        def worker(i):
            r = brain.ask(f"question {i}", mode="ASSISTANT", session_id=f"s{i}")
            with lock:
                results.append(r.success)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(results), 20)
        self.assertTrue(all(results))
        brain.stop()

    def test_never_controls_hardware_or_modes(self):
        # the brain module must not import behavior/mode/hardware managers
        import ast, brain.brain_manager as m
        tree = ast.parse(open(m.__file__).read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
        self.assertFalse(any(("behavior" in x or "mode." in x or "hardware" in x
                              or "emotion" in x) for x in mods))

if __name__ == "__main__":
    unittest.main()
