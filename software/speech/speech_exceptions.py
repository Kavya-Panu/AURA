"""
speech/speech_exceptions.py
===========================
Speech-layer exceptions, rooted in the project's AuraError.
"""
from __future__ import annotations

from core.exceptions import AuraError


class SpeechError(AuraError):
    """Base class for all Speech Manager errors."""


class TTSError(SpeechError):
    """A TTS engine failed to synthesize."""


class TTSUnavailable(TTSError):
    """The selected TTS engine is not available (missing library/voice)."""


class PlaybackError(SpeechError):
    """Audio playback failed."""


class SpeechCancelled(SpeechError):
    """The current utterance was cancelled/interrupted."""


class VoiceProfileError(SpeechError):
    """An unknown or invalid voice profile was requested."""
