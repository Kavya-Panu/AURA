"""
intent/intent_parser.py
=======================
Normalisation + extraction pipeline: raw text -> ParsedUtterance (normalised
text, wake-word flag, tokens, extracted parameters). No classification here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent_exceptions import IntentParseError
from .natural_language import normalize, strip_wake_word, tokenize
from .parameter_extractor import extract


@dataclass(frozen=True)
class ParsedUtterance:
    """The parser's output, consumed by the matcher/engine."""
    raw: str
    normalized: str
    had_wake_word: bool
    tokens: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


class IntentParser:
    """Stateless text -> ParsedUtterance transformer."""

    def parse(self, text: str) -> ParsedUtterance:
        if not text or not text.strip():
            raise IntentParseError("Empty input text")
        normalized = normalize(text)
        normalized, had_wake = strip_wake_word(normalized)
        normalized = normalized.strip()
        if not normalized:
            raise IntentParseError("Nothing after the wake word",
                                   {"raw": text})
        tokens = tokenize(normalized)
        params = extract(normalized, tokens)
        return ParsedUtterance(raw=text, normalized=normalized,
                               had_wake_word=had_wake,
                               tokens=tokens, params=params)
