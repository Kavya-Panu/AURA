import unittest
from brain.provider_registry import ProviderRegistry, MockProvider
from brain.provider_selector import ProviderSelector
from brain.brain_config import SelectionRules, TaskKind
from brain.brain_exceptions import NoProviderAvailable

def registry(*specs):
    reg = ProviderRegistry()
    for name, kw in specs:
        reg.register(MockProvider(name, **kw))
    return reg

class TestSelection(unittest.TestCase):
    def setUp(self):
        self.reg = registry(("ollama", {"is_local": True}),
                            ("claude", {}), ("openai", {}))
        self.rules = SelectionRules(by_task={
            TaskKind.SIMPLE_QA.value: ["ollama", "openai"],
            TaskKind.COMPLEX_REASONING.value: ["claude", "openai"],
            TaskKind.TRANSLATION.value: ["ollama"],
        }, default_chain=["openai", "ollama"])
        self.sel = ProviderSelector(self.reg, self.rules)

    def test_simple_qa_prefers_local(self):
        self.assertEqual(self.sel.select(TaskKind.SIMPLE_QA), "ollama")

    def test_complex_prefers_cloud(self):
        self.assertEqual(self.sel.select(TaskKind.COMPLEX_REASONING), "claude")

    def test_translation_local(self):
        self.assertEqual(self.sel.select(TaskKind.TRANSLATION), "ollama")

    def test_chain_includes_fallbacks(self):
        chain = self.sel.candidate_chain(TaskKind.SIMPLE_QA)
        self.assertEqual(chain[0], "ollama")
        self.assertIn("claude", chain)   # other available providers appended

    def test_unavailable_filtered_out(self):
        self.reg.get("ollama").set_available(False)
        chain = self.sel.candidate_chain(TaskKind.SIMPLE_QA)
        self.assertNotIn("ollama", chain)
        self.assertEqual(chain[0], "openai")

    def test_offline_prefers_local(self):
        chain = self.sel.candidate_chain(TaskKind.COMPLEX_REASONING, offline=True)
        self.assertEqual(chain[0], "ollama")   # local floated to front

    def test_no_provider_raises(self):
        for n in ("ollama", "claude", "openai"):
            self.reg.get(n).set_available(False)
        with self.assertRaises(NoProviderAvailable):
            self.sel.candidate_chain(TaskKind.SIMPLE_QA)

if __name__ == "__main__":
    unittest.main()
