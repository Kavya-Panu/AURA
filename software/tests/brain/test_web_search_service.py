"""Web search intent, sanitisation, prompt safety, and brain integration."""
import unittest

from brain import BrainManager, MockProvider, WebSearchService
from brain.brain_config import BrainConfig
from core.event_bus import EventBus


RESULTS = [
    {
        "title": "Example current result",
        "href": "https://example.com/current",
        "body": "The verified current answer is Example A.",
    },
    {
        "title": "Second source",
        "href": "https://example.org/report",
        "body": "A second report also says Example A.",
    },
]


class TestWebSearchService(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_search(query, max_results):
            self.calls.append((query, max_results))
            return RESULTS

        self.search = WebSearchService(search=fake_search, max_results=3)

    def test_routes_explicit_and_fresh_questions_only(self):
        self.assertTrue(self.search.needs_search("Search the web for ESP32 news"))
        self.assertTrue(self.search.needs_search("Who won yesterday's match?"))
        self.assertTrue(self.search.needs_search(
            "Give me five international news stories"
        ))
        self.assertTrue(self.search.needs_search("What are today's headlines?"))
        self.assertTrue(self.search.needs_search("Who is the prime minister?"))
        self.assertTrue(self.search.needs_search(
            "Who is the current UK prime minister?"
        ))
        self.assertFalse(self.search.needs_search("Explain Ohm's law"))
        self.assertFalse(self.search.needs_search("What is electric current?"))

    def test_cleans_explicit_search_phrase_and_caches(self):
        first = self.search.search("Please search the internet for ESP32 S3 news")
        second = self.search.search("Please search the internet for ESP32 S3 news")
        self.assertTrue(first.success)
        self.assertEqual(first.query, "ESP32 S3 news")
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 1)

    def test_context_marks_snippets_untrusted(self):
        context = self.search.build_context(self.search.search("latest ESP32 news"))
        self.assertIn("untrusted", context)
        self.assertIn("https://example.com/current", context)
        self.assertIn("at most two short sentences", context)

    def test_brain_uses_search_context_and_exposes_sources(self):
        captured = []

        def respond(request):
            captured.append(request)
            return "Example A is the current answer."

        cfg = BrainConfig.default()
        brain = BrainManager(
            EventBus(),
            cfg,
            web_search_service=self.search,
        )
        brain.register_provider(MockProvider("ollama", is_local=True, responder=respond))
        brain.initialize()
        result = brain.ask("What is the latest example update?", mode="ASSISTANT")
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["task"], "web_search")
        self.assertEqual(len(result.metadata["sources"]), 2)
        self.assertIn("LIVE WEB SEARCH CONTEXT", captured[0].system_prompt)
        brain.stop()


if __name__ == "__main__":
    unittest.main()
