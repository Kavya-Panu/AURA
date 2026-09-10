import unittest
from brain.provider_registry import (
    MockProvider, ProviderRegistry, AIProvider, GenerationRequest,
    OpenAIProvider, ClaudeProvider, OllamaProvider)
from brain.brain_config import ProviderConfig
from brain.brain_exceptions import ProviderError, ProviderUnavailable

REQ = GenerationRequest("sys", ({"role": "user", "content": "hello"},))

class TestProviders(unittest.TestCase):
    def test_mock_is_provider(self):
        self.assertIsInstance(MockProvider(), AIProvider)

    def test_mock_generates(self):
        r = MockProvider("m").generate(REQ)
        self.assertTrue(r.success)
        self.assertIn("hello", r.response)
        self.assertEqual(r.provider, "m")

    def test_mock_unavailable_raises(self):
        with self.assertRaises(ProviderUnavailable):
            MockProvider("m", available=False).generate(REQ)

    def test_mock_fail_raises(self):
        with self.assertRaises(ProviderError):
            MockProvider("m", fail=True).generate(REQ)

    def test_real_providers_satisfy_interface(self):
        # constructed without SDKs present; they are AIProviders and report
        # unavailable rather than crashing at import.
        for cls in (OpenAIProvider, ClaudeProvider, OllamaProvider):
            p = cls(ProviderConfig(cls.__name__.lower(), "model"))
            self.assertIsInstance(p, AIProvider)
            self.assertFalse(p.is_available())   # no SDK / no client in sandbox

    def test_registry_register_and_available(self):
        reg = ProviderRegistry()
        reg.register(MockProvider("a"))
        reg.register(MockProvider("b", available=False))
        self.assertEqual(set(reg.names()), {"a", "b"})
        self.assertEqual(reg.available(), ("a",))     # b is unavailable

    def test_registry_rejects_non_provider(self):
        with self.assertRaises(ProviderError):
            ProviderRegistry().register(object())

if __name__ == "__main__":
    unittest.main()
