import unittest
from memory.memory_search import MemorySearch, SearchQuery
from memory.memory_config import SearchConfig
from memory.memory_record import MemoryRecord, MemoryType, Importance

def recs():
    return [
        MemoryRecord(MemoryType.FACT, {"text": "Sky likes physics"},
                     Importance.HIGH, tags=("subject", "science")),
        MemoryRecord(MemoryType.FACT, {"text": "Sky dislikes mornings"},
                     Importance.LOW, tags=("habit",)),
        MemoryRecord(MemoryType.QUIZ_RESULT, {"topic": "physics", "score": 90},
                     Importance.MEDIUM, created_at=500.0),
        MemoryRecord(MemoryType.QUIZ_RESULT, {"topic": "math", "score": 70},
                     Importance.MEDIUM, created_at=1500.0),
    ]

class TestSearch(unittest.TestCase):
    def setUp(self):
        self.s = MemorySearch(SearchConfig())
        self.r = recs()

    def test_keyword(self):
        hits = self.s.search(self.r, SearchQuery(text="physics"))
        self.assertTrue(hits)
        self.assertTrue(all("physics" in str(h.record.content).lower()
                            or h.record.memory_type == MemoryType.FACT for h in hits))

    def test_type_filter(self):
        hits = self.s.search(self.r, SearchQuery(memory_type=MemoryType.QUIZ_RESULT))
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h.record.memory_type == MemoryType.QUIZ_RESULT for h in hits))

    def test_tag_search(self):
        hits = self.s.search(self.r, SearchQuery(tags=("science",)))
        self.assertEqual(len(hits), 1)

    def test_importance_filter(self):
        hits = self.s.search(self.r, SearchQuery(min_importance=Importance.HIGH))
        self.assertTrue(all(h.record.importance.value >= Importance.HIGH.value
                            for h in hits))

    def test_time_range(self):
        hits = self.s.search(self.r, SearchQuery(created_after=1000.0))
        self.assertTrue(all(h.record.created_at >= 1000.0 for h in hits))

    def test_ranking_prefers_importance(self):
        # equal keyword match; higher importance should rank first
        hits = self.s.search(self.r, SearchQuery(text="Sky"))
        self.assertEqual(hits[0].record.importance, Importance.HIGH)

    def test_limit(self):
        hits = self.s.search(self.r, SearchQuery(limit=1))
        self.assertEqual(len(hits), 1)

    def test_semantic_hook_used(self):
        def hook(text, cands):
            # boost the math quiz artificially
            return {c.memory_id: (1.0 if c.content.get("topic") == "math" else 0.0)
                    for c in cands}
        s = MemorySearch(SearchConfig(), semantic_hook=hook)
        # "quiz" is a substring of the "quiz_result" type in both haystacks, so
        # both quiz records are candidates; the hook then re-ranks math first.
        hits = s.search(self.r, SearchQuery(text="quiz"))
        self.assertEqual(hits[0].record.content.get("topic"), "math")

if __name__ == "__main__":
    unittest.main()
