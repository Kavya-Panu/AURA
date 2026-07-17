"""
intent/utils.py
===============
Small shared helpers (kept free of any intent-specific knowledge).
"""
from __future__ import annotations


def clamp(value: float, lo: float, hi: float) -> float:
    """Constrain value to [lo, hi]."""
    return lo if value < lo else hi if value > hi else value


def overlap_ratio(utterance: set[str], pattern: set[str]) -> float:
    """Fraction of the pattern's tokens present in the utterance (0..1)."""
    if not pattern:
        return 0.0
    return len(utterance & pattern) / len(pattern)


def is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """True if needle's tokens appear in haystack in order (gaps allowed)."""
    it = iter(haystack)
    return all(tok in it for tok in needle)
