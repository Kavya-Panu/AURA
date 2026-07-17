"""
intent/parameter_extractor.py
=============================
Deterministic slot extraction from normalised text: durations, timer values,
languages (incl. "X to Y" pairs), subjects, topics, difficulty, dates, times,
reminders, question counts, memory values and calculator expressions.

Everything is regex/dictionary based - no ML, no network - so extraction is
microseconds-fast and fully predictable.
"""
from __future__ import annotations

import re
from typing import Any

from .synonym_dictionary import (
    DIFFICULTY,
    LANGUAGES,
    SUBJECTS,
    SUBJECT_CANON,
)

# ---- Durations ---------------------------------------------------------------
_HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b")
_MINS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)\b")
_SECS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b")
_HALF_HOUR_RE = re.compile(r"\bhalf\s+(?:an\s+)?hour\b")
_AN_HOUR_RE = re.compile(r"\ban?\s+hour\b")
_A_MINUTE_RE = re.compile(r"\ba\s+minute\b")

# ---- Times / dates -----------------------------------------------------------
_TIME_RE = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b")
_TIME_24_RE = re.compile(r"\bat\s+(\d{1,2}):(\d{2})\b")
_DATE_WORDS = ("tomorrow", "today", "tonight")
_NEXT_DAY_RE = re.compile(
    r"\b(?:next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")

# ---- Misc --------------------------------------------------------------------
_QCOUNT_RE = re.compile(r"\b(\d+)\s+questions?\b")
_REMIND_RE = re.compile(
    r"\bremind me\s+(?:to\s+|about\s+)?(.*?)(?=\s+at\s+\d|\s+tomorrow\b|\s+tonight\b|\s+next\b|$)")
_REMEMBER_RE = re.compile(r"\b(?:remember|note)\s+(?:that\s+|down\s+)?(.+)$")
_FORGET_RE = re.compile(r"\bforget\s+(?:about\s+|what i (?:told|said).*about\s+)?(.+)$")
_TOPIC_RE = re.compile(r"\b(?:about|on|regarding)\s+([a-z][a-z ]{1,40})$")
_TEACH_RE = re.compile(
    r"\b(?:teach me|learn|explain|tutor me on|study)\s+(?:about\s+|how\s+)?([a-z][a-z ]{1,40})$")
_EXPR_TOKEN = re.compile(r"^(?:\d+(?:\.\d+)?%?|plus|minus|times|x|of|percent|divided|by|[-+*/])$")


def _duration_minutes(text: str) -> int | None:
    """Total minutes expressed in the text, or None."""
    total = 0.0
    found = False
    if _HALF_HOUR_RE.search(text):
        total += 30; found = True
    elif _AN_HOUR_RE.search(text):
        total += 60; found = True
    for m in _HOURS_RE.finditer(text):
        total += float(m.group(1)) * 60; found = True
    for m in _MINS_RE.finditer(text):
        total += float(m.group(1)); found = True
    if _A_MINUTE_RE.search(text):
        total += 1; found = True
    return int(round(total)) if found and total > 0 else None


def _timer_seconds(text: str) -> int | None:
    """Seconds for SET_TIMER: explicit seconds, else duration in minutes."""
    secs = 0.0
    found = False
    for m in _SECS_RE.finditer(text):
        secs += float(m.group(1)); found = True
    mins = _duration_minutes(text)
    if mins is not None:
        secs += mins * 60; found = True
    return int(round(secs)) if found and secs > 0 else None


def _languages(tokens: list[str]) -> dict[str, str]:
    """Language pair / target from token order. 'english to japanese' ->
    source+target; a single language -> target."""
    hits = [(i, LANGUAGES[t]) for i, t in enumerate(tokens) if t in LANGUAGES]
    out: dict[str, str] = {}
    if len(hits) >= 2:
        out["source_language"] = hits[0][1]
        out["target_language"] = hits[1][1]
    elif len(hits) == 1:
        out["target_language"] = hits[0][1]
    return out


def _subject(text: str) -> str | None:
    for s in SUBJECTS:                    # multi-word entries listed first
        if re.search(rf"\b{re.escape(s)}\b", text):
            return SUBJECT_CANON.get(s, s)
    return None


def _difficulty(tokens: list[str]) -> str | None:
    for t in tokens:
        if t in DIFFICULTY:
            return DIFFICULTY[t]
    return None


def _time_of_day(text: str) -> str | None:
    m = _TIME_RE.search(text)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3) == "pm":
            hour += 12
        minute = int(m.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"
    m = _TIME_24_RE.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return None


def _date_word(text: str) -> str | None:
    for w in _DATE_WORDS:
        if re.search(rf"\b{w}\b", text):
            return w
    m = _NEXT_DAY_RE.search(text)
    return m.group(0) if m else None


def _expression(tokens: list[str]) -> str | None:
    """Longest run of calculator-ish tokens ('15% of 240', '12 times 9')."""
    best: list[str] = []
    run: list[str] = []
    for t in tokens:
        if _EXPR_TOKEN.match(t):
            run.append(t)
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(run) > len(best):
        best = run
    return " ".join(best) if len(best) >= 2 and any(
        any(c.isdigit() for c in t) for t in best) else None


def extract(text: str, tokens: list[str]) -> dict[str, Any]:
    """Extract every recognisable parameter from normalised text."""
    params: dict[str, Any] = {}

    if (d := _duration_minutes(text)) is not None:
        params["duration_minutes"] = d
    if (ts := _timer_seconds(text)) is not None:
        params["timer_seconds"] = ts
    params.update(_languages(tokens))
    if (s := _subject(text)) is not None:
        params["subject"] = s
    if (df := _difficulty(tokens)) is not None:
        params["difficulty"] = df
    if (t := _time_of_day(text)) is not None:
        params["reminder_time"] = t
    if (dw := _date_word(text)) is not None:
        params.setdefault("reminder_time", dw)
        params["date"] = dw
    if (m := _QCOUNT_RE.search(text)):
        params["question_count"] = int(m.group(1))
    if (m := _REMIND_RE.search(text)) and m.group(1).strip():
        params["reminder_text"] = m.group(1).strip()
    if (m := _REMEMBER_RE.search(text)) and m.group(1).strip():
        params["memory_value"] = m.group(1).strip()
    if (m := _FORGET_RE.search(text)) and m.group(1).strip():
        params["memory_key"] = m.group(1).strip()
    if (m := _TOPIC_RE.search(text)):
        params["topic"] = m.group(1).strip()
    elif (m := _TEACH_RE.search(text)):
        params["topic"] = m.group(1).strip()
    if (e := _expression(tokens)) is not None:
        params["expression"] = e

    params["query"] = text                # always available for free-text uses
    return params
