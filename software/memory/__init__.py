"""
memory - AURA's Memory Manager (long-term memory / persistence layer).

Stores, retrieves, updates, deletes, searches, summarizes and forgets memories,
and publishes memory events. It ONLY manages memory: it never generates AI
responses, reasons, controls hardware, or changes emotions/modes. The Brain
Manager talks to the MemoryManager, never to a storage provider directly.

Usage::

    from memory import MemoryManager, MemoryConfig, MemoryType, Importance
    from memory.memory_provider import SQLiteProvider
    mem = MemoryManager(bus, MemoryConfig(), provider=SQLiteProvider("aura.db"))
    lifecycle.register(mem)                       # it is a core Module
    rec = mem.store(MemoryType.USER_PROFILE, {"name": "Sky"},
                    importance=Importance.CRITICAL)
    hits = mem.search(SearchQuery(text="Sky"))
"""
from .memory_config import (
    CleanupConfig, MemoryConfig, RetentionPolicy, SearchConfig,
    SummarizationConfig,
)
from .memory_manager import MemoryManager, Summarizer
from .memory_provider import (
    InMemoryProvider, JSONProvider, MemoryProvider, SQLiteProvider,
    VectorProvider,
)
from .memory_record import Importance, MemoryRecord, MemoryType
from .memory_search import MemorySearch, SearchHit, SearchQuery

__all__ = [
    "MemoryManager", "Summarizer", "MemoryConfig", "RetentionPolicy",
    "CleanupConfig", "SearchConfig", "SummarizationConfig",
    "MemoryProvider", "InMemoryProvider", "JSONProvider", "SQLiteProvider",
    "VectorProvider", "MemoryRecord", "MemoryType", "Importance",
    "MemorySearch", "SearchQuery", "SearchHit",
]
