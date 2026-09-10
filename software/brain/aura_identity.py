"""Accurate, local self-description for the AURA robot.

Identity questions are answered from this profile instead of asking the LLM.
That keeps the answer fast and prevents the model from inventing hardware or
features that are not part of the current prototype.
"""
from __future__ import annotations

import re


AURA_SYSTEM_OVERVIEW = (
    "I am AURA, your AI desktop companion robot. Say Hey AURA and ask me a "
    "question; I listen, understand your speech, find an answer, and speak it "
    "back to you. I can show different emotions, blink naturally, follow your "
    "face with my eyes, help you study, explain topics, answer questions, and "
    "use a focus mode while you work. My screen and audio hardware handle my "
    "expressions, listening, and voice, while my connected computer provides "
    "the intelligence that helps me respond."
)


_IDENTITY_PATTERNS = (
    r"\bwhat are you\b",
    r"\bwho are you\b",
    r"\btell me about yourself\b",
    r"\bexplain yourself\b",
    r"\bwhat can you do\b",
    r"\bwhat are your features\b",
    r"\bwhat features do you have\b",
    r"\bexplain your (?:system|program|software|hardware|architecture)\b",
    r"\bhow (?:do|does) (?:you|aura) work\b",
    r"\bdescribe (?:your|aura(?:'s)?) (?:system|features|program|architecture)\b",
)


def is_aura_identity_question(text: str) -> bool:
    """Return True when the user is asking AURA to explain itself."""
    normalized = re.sub(r"[^a-z0-9']+", " ", (text or "").lower()).strip()
    return any(re.search(pattern, normalized) for pattern in _IDENTITY_PATTERNS)
