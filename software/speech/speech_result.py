"""
speech/speech_result.py
=======================
The result type the Speech Manager returns for one utterance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SpeechResult:
    """Outcome of speaking one message.

    Attributes:
        text: The text that was (or would be) spoken.
        emotion: The emotion token used on the face (e.g. "HAPPY", "THINK").
        profile: The voice profile name used.
        engine: The TTS engine that synthesized it.
        duration_s: Approximate spoken duration.
        spoken: True if playback completed; False if cancelled/failed.
        cancelled: True if interrupted before finishing.
        error: Error message on failure.
        metadata: Free-form extras (queue position, priority, ...).
    """
    text: str = ""
    emotion: str = "NORMAL"
    profile: str = ""
    engine: str = ""
    duration_s: float = 0.0
    spoken: bool = True
    cancelled: bool = False
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def failure(error: str, text: str = "") -> "SpeechResult":
        return SpeechResult(text=text, spoken=False, error=error)

    @staticmethod
    def cancelled_result(text: str = "") -> "SpeechResult":
        return SpeechResult(text=text, spoken=False, cancelled=True)
