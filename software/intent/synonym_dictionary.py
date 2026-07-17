"""
intent/synonym_dictionary.py
============================
Synonym groups used by the matcher. Every surface token is mapped to a
canonical *token class* via ``token_class``; BOTH utterance tokens and pattern
tokens go through the same mapping, so "concentrate", "study" and "focus" all
land on the same class and match each other.

Also hosts the language / subject / difficulty vocabularies used by the
parameter extractor and validator.
"""
from __future__ import annotations

# ---- verb / concept synonym groups (surface -> class) -----------------------
_GROUPS: dict[str, tuple[str, ...]] = {
    "focus": ("focus", "focusing", "concentrate", "concentrating", "study",
              "studying", "revise", "revising", "revision"),
    "start": ("start", "starting", "begin", "beginning", "launch", "enter",
              "activate", "initiate", "open"),
    "stop": ("stop", "end", "ending", "finish", "finished", "done", "exit",
             "quit", "terminate", "enough"),
    "pause": ("pause", "paused", "hold"),
    "resume": ("resume", "continue", "unpause", "proceed"),
    "next": ("next", "skip", "following"),
    "repeat": ("repeat", "again"),
    "help": ("help", "assist", "aid"),
    "teach": ("teach", "tutor", "instruct"),
    "learn": ("learn", "learning"),
    "explain": ("explain", "explaining", "clarify"),
    "translate": ("translate", "translating", "translation", "interpreter",
                  "interpret"),
    "quiz": ("quiz", "quizzes", "test", "examine"),
    "question": ("question", "questions"),
    "remember": ("remember", "memorize", "memorise", "note", "save"),
    "forget": ("forget", "delete", "remove", "erase"),
    "timer": ("timer", "countdown"),
    "remind": ("remind", "reminder", "reminders"),
    "hello": ("hi", "hello", "hey", "greetings", "yo"),
    "thanks": ("thanks", "thank", "thx", "cheers"),
    "praise": ("awesome", "amazing", "great", "brilliant", "best", "fantastic",
               "wonderful"),
    "insult": ("hate", "stupid", "dumb", "useless", "terrible", "worst"),
    "tired": ("tired", "exhausted", "sleepy", "drained"),
    "stressed": ("stressed", "overwhelmed", "anxious", "stressing"),
    "bored": ("bored", "boring"),
    "score": ("score", "points", "result"),
    "hint": ("hint", "clue"),
    "weather": ("weather", "forecast", "rain", "sunny"),
    "calculate": ("calculate", "compute", "calc"),
    "search": ("search", "google", "lookup", "find"),
    "quiet": ("quiet", "silence", "shush", "hush", "mute"),
    "summarize": ("summarize", "summarise", "summary", "recap"),
    "simplify": ("simplify", "simpler", "simple"),
    "example": ("example", "examples", "instance"),
    "answer": ("answer", "answers", "solution"),
    "sleep": ("sleep", "goodnight", "nap"),
    "wake": ("wake", "awake"),
    "battery": ("battery", "charge", "charged", "power"),
    "music": ("music", "song", "songs", "playlist"),
    "joke": ("joke", "jokes", "funny", "laugh"),
    "motivate": ("motivate", "motivation", "encourage", "encouragement",
                 "push"),
    "homework": ("homework", "assignment", "assignments", "coursework"),
    "break": ("break", "rest", "breather"),
    "stuck": ("stuck", "confused", "lost"),
    "check": ("check", "verify", "correct", "right"),
    "look": ("look", "looking", "watch"),
    "follow": ("follow", "track", "following", "tracking"),
    "louder": ("louder", "loud"),
    "quieter": ("quieter", "softer", "lower"),
}

# Flattened surface -> class lookup.
_CANON: dict[str, str] = {
    surface: cls for cls, surfaces in _GROUPS.items() for surface in surfaces
}


def token_class(token: str) -> str:
    """Map a surface token to its canonical class (or itself)."""
    return _CANON.get(token, token)


# ---- Languages (name + aliases -> canonical) --------------------------------
LANGUAGES: dict[str, str] = {
    "english": "English", "spanish": "Spanish", "japanese": "Japanese",
    "hindi": "Hindi", "french": "French", "german": "German",
    "italian": "Italian", "chinese": "Chinese", "mandarin": "Chinese",
    "korean": "Korean", "portuguese": "Portuguese", "russian": "Russian",
    "arabic": "Arabic", "urdu": "Urdu", "punjabi": "Punjabi",
    "bengali": "Bengali", "tamil": "Tamil", "dutch": "Dutch",
    "turkish": "Turkish", "polish": "Polish", "greek": "Greek",
}

# ---- Subjects (multi-word first for greedy matching) -------------------------
SUBJECTS: tuple[str, ...] = (
    "computer science", "software engineering", "electrical engineering",
    "machine learning", "artificial intelligence",
    "math", "maths", "mathematics", "algebra", "calculus", "geometry",
    "physics", "chemistry", "biology", "science", "electronics", "circuits",
    "history", "geography", "economics", "english", "literature",
    "programming", "python", "statistics", "psychology", "philosophy",
)

SUBJECT_CANON: dict[str, str] = {
    "maths": "math", "mathematics": "math",
}

# ---- Difficulty --------------------------------------------------------------
DIFFICULTY: dict[str, str] = {
    "easy": "beginner", "beginner": "beginner", "basic": "beginner",
    "medium": "intermediate", "intermediate": "intermediate",
    "normal": "intermediate",
    "hard": "advanced", "difficult": "advanced", "advanced": "advanced",
    "expert": "advanced",
}

# ---- Filler tokens ignored by the generic resolver ---------------------------
FILLER: frozenset[str] = frozenset({
    "aura", "please", "now", "the", "a", "an", "it", "that", "this", "im",
    "were", "ok", "okay", "lets", "just", "can", "you", "me", "my", "for",
    "to", "and",
})
