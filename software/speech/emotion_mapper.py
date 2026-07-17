"""
speech/emotion_mapper.py
========================
Maps a BrainResult (or an answer's content/mode) to a face emotion token and a
voice profile. This is the bridge from "what was said" to "how AURA looks and
sounds while saying it". It returns emotion TOKENS that match the core Emotion
enum values (the ESP32 serial tokens) - it never renders anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.constants import Emotion


@dataclass(frozen=True)
class SpeakingStyle:
    """How to express one utterance."""
    emotion: str          # face token, e.g. "HAPPY", "THINK"
    profile: str          # voice profile name


# Per-mode base style (mode -> (emotion token, voice profile)).
_MODE_STYLE: dict[str, tuple[str, str]] = {
    "TEACHER":      (Emotion.NORMAL.value, "teacher"),
    "HOMEWORK":     (Emotion.HAPPY.value, "teacher"),
    "QUIZ":         (Emotion.EXCITED.value, "excited"),
    "TRANSLATION":  (Emotion.LISTENING.value, "translator"),
    "FOCUS":        (Emotion.NORMAL.value, "calm"),
    "PRESENTATION": (Emotion.NORMAL.value, "assistant"),
    "ASSISTANT":    (Emotion.NORMAL.value, "assistant"),
    "NORMAL":       (Emotion.HAPPY.value, "friendly"),
}

# Content cues -> emotion token. Checked in order; first match wins.
_CONTENT_CUES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(congrat|well done|great job|you did it|excellent)\b", re.I),
     Emotion.CELEBRATE.value),
    (re.compile(r"\b(sorry|apolog|unfortunately|i can't|cannot)\b", re.I),
     Emotion.SAD.value),
    (re.compile(r"\b(hmm|let me think|thinking|one moment)\b", re.I),
     Emotion.THINKING.value),
    (re.compile(r"\b(not sure|unclear|confus|i don't understand)\b", re.I),
     Emotion.CONFUSED.value),
    (re.compile(r"\b(careful|reminder|stay focused|put your phone|distract)\b", re.I),
     Emotion.WORRIED.value),
    (re.compile(r"\b(love|wonderful|amazing|so happy)\b", re.I),
     Emotion.LOVE.value),
    (re.compile(r"\b(hello|hi there|welcome|good morning|good evening)\b", re.I),
     Emotion.HAPPY.value),
]


class EmotionMapper:
    """Chooses a face emotion + voice profile for an utterance."""

    def __init__(self, default_profile: str = "friendly") -> None:
        self._default_profile = default_profile

    def map(self, text: str, *, mode: str | None = None,
            hint_emotion: str | None = None) -> SpeakingStyle:
        """Return the SpeakingStyle for this utterance.

        Precedence: explicit hint > strong content cue > mode base > default.
        """
        base_emotion, profile = _MODE_STYLE.get(
            (mode or "NORMAL").upper(),
            (Emotion.NORMAL.value, self._default_profile))

        emotion = base_emotion
        # Content cues can override the mode's neutral base (but translation
        # stays neutral/listening to avoid distracting expression churn).
        if (mode or "").upper() != "TRANSLATION":
            for pattern, cue_emotion in _CONTENT_CUES:
                if pattern.search(text):
                    emotion = cue_emotion
                    break

        if hint_emotion:
            emotion = hint_emotion.upper()

        return SpeakingStyle(emotion=emotion, profile=profile)
