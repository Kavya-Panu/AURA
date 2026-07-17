"""
intent/natural_language.py
==========================
Text normalisation: lowercase, apostrophe folding ("let's" -> "lets"),
punctuation stripping (colons kept for times), wake-word stripping, and
word-number conversion ("two hours" -> "2 hours").
"""
from __future__ import annotations

import re

_WAKE_RE = re.compile(r"^\s*(?:hey\s+|ok\s+|okay\s+)?aura\b[\s,!.:;-]*",
                      re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w:%+\-*/.]+")   # keep : % + - * / . for times/math
_WS_RE = re.compile(r"\s+")

_WORD_NUM: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "ninety": "90",
}


def strip_wake_word(text: str) -> tuple[str, bool]:
    """Remove a leading wake phrase. Returns (text, had_wake_word)."""
    stripped = _WAKE_RE.sub("", text, count=1)
    return stripped, stripped != text


def normalize(text: str) -> str:
    """Lowercase, fold apostrophes, strip punctuation, convert word-numbers,
    collapse whitespace. The result is the matching/extraction surface."""
    text = text.lower().strip()
    text = text.replace("’", "").replace("'", "")     # let's -> lets
    text = _PUNCT_RE.sub(" ", text)
    tokens = [_WORD_NUM.get(tok, tok) for tok in text.split()]
    return _WS_RE.sub(" ", " ".join(tokens)).strip()


def tokenize(normalized: str) -> list[str]:
    """Split a normalised string into tokens."""
    return normalized.split() if normalized else []
