"""
intent/clarification.py
=======================
Clarification questions: (a) per missing parameter, exactly per the spec's
examples; (b) low-confidence "did you mean" prompts for the 0.40-0.70 band.
"""
from __future__ import annotations

from .intent_types import Intent

# (intent, parameter) -> question. Falls back to the parameter-level default.
_PARAM_QUESTIONS: dict[tuple[Intent, str], str] = {
    (Intent.START_FOCUS, "duration_minutes"):
        "How long would you like to focus?",
    (Intent.START_TRANSLATION, "target_language"):
        "Which languages would you like to use?",
    (Intent.SET_TRANSLATION_LANGUAGE, "target_language"):
        "Which language should I translate to?",
    (Intent.SET_REMINDER, "reminder_text"):
        "What should I remind you about?",
    (Intent.SET_REMINDER, "reminder_time"):
        "When should I remind you?",
    (Intent.START_TEACHING, "subject"):
        "What would you like to learn about?",
    (Intent.MEMORY_REMEMBER, "memory_value"):
        "What should I remember?",
    (Intent.SET_TIMER, "timer_seconds"):
        "For how long should I set the timer?",
    (Intent.SET_FOCUS_DURATION, "duration_minutes"):
        "How long should the session be?",
    (Intent.CALCULATE, "expression"):
        "What should I calculate?",
    (Intent.WEB_SEARCH, "query"):
        "What should I search for?",
}

_DEFAULT_PARAM_QUESTION: dict[str, str] = {
    "duration_minutes": "For how long?",
    "target_language": "Which language?",
    "subject": "Which subject?",
    "query": "Could you give me more detail?",
}

# Human phrasings for "did you mean ...?" prompts.
_INTENT_PHRASE: dict[Intent, str] = {
    Intent.START_FOCUS: "start a focus session",
    Intent.START_TRANSLATION: "start live translation",
    Intent.START_TEACHING: "start a lesson",
    Intent.START_QUIZ: "start a quiz",
    Intent.START_HOMEWORK: "get homework help",
    Intent.STOP_FOCUS: "end the focus session",
    Intent.SET_TIMER: "set a timer",
    Intent.SET_REMINDER: "set a reminder",
}


def question_for_missing(intent: Intent, parameter: str) -> str:
    """The clarification question for one missing parameter."""
    return _PARAM_QUESTIONS.get(
        (intent, parameter),
        _DEFAULT_PARAM_QUESTION.get(parameter, f"Could you tell me the {parameter.replace('_', ' ')}?"))


def question_for_low_confidence(intent: Intent) -> str:
    """A gentle confirm question for the 0.40-0.70 confidence band."""
    phrase = _INTENT_PHRASE.get(
        intent, intent.value.replace("_", " ").lower())
    return f"Did you mean to {phrase}?"
