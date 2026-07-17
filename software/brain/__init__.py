"""
brain - AURA's intelligence layer (the Brain Manager).

Generates text responses only: it never controls hardware, changes emotions or
modes, speaks, or does speech recognition. It selects among pluggable AI
providers (OpenAI/Claude/Qwen/DeepSeek/Ollama + a Mock for offline/tests),
manages conversation history, builds per-mode prompts, and handles translation
and knowledge tasks with timeout/retry/fallback/caching.

Usage::

    from brain import BrainManager, BrainConfig
    from brain.provider_registry import MockProvider
    brain = BrainManager(bus, BrainConfig.default())
    brain.register_provider(MockProvider("ollama", is_local=True))
    lifecycle.register(brain)                 # it is a core Module
    result = brain.ask("What is Ohm's law?", mode="TEACHER")
"""
from .brain_config import BrainConfig, ProviderConfig, SelectionRules, TaskKind
from .brain_context import BrainContext, BrainSnapshot
from .brain_manager import BrainManager
from .brain_result import BrainResult, TokenUsage
from .knowledge_service import KnowledgeRequest
from .provider_registry import (
    AIProvider, GenerationRequest, MockProvider, ProviderRegistry,
)

__all__ = [
    "BrainManager", "BrainConfig", "ProviderConfig", "SelectionRules",
    "TaskKind", "BrainResult", "TokenUsage", "BrainContext", "BrainSnapshot",
    "AIProvider", "GenerationRequest", "MockProvider", "ProviderRegistry",
    "KnowledgeRequest",
]
