"""
brain/brain_result.py
=====================
The result type the Brain Manager returns. Generic across providers and tasks.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting for one generation."""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class BrainResult:
    """The output of a Brain request.

    Attributes:
        response: The generated text (empty on failure).
        provider: Name of the provider that produced it.
        confidence: 0..1 heuristic confidence.
        processing_time: Wall-clock seconds spent.
        tokens: Token usage.
        reasoning_summary: Optional short summary of the reasoning (never the
            full chain-of-thought; a brief rationale only).
        translation: Populated for translation requests (translated text).
        success: Whether generation succeeded.
        error: Error message when success is False.
        metadata: Free-form extra data (task kind, cache hit, fallbacks tried).
    """
    response: str = ""
    provider: str = ""
    confidence: float = 0.0
    processing_time: float = 0.0
    tokens: TokenUsage = field(default_factory=TokenUsage)
    reasoning_summary: str = ""
    translation: str = ""
    success: bool = True
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def failure(error: str, provider: str = "", **meta: Any) -> "BrainResult":
        return BrainResult(success=False, error=error, provider=provider,
                           confidence=0.0, metadata=meta)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "provider": self.provider,
            "confidence": round(self.confidence, 3),
            "processing_time": round(self.processing_time, 3),
            "tokens": {"prompt": self.tokens.prompt_tokens,
                       "completion": self.tokens.completion_tokens,
                       "total": self.tokens.total},
            "reasoning_summary": self.reasoning_summary,
            "translation": self.translation,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }
