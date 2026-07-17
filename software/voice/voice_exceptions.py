"""
voice/voice_exceptions.py
=========================
Voice-System-specific exceptions, rooted in the project's AuraError.
"""
from __future__ import annotations

from core.exceptions import AuraError


class VoiceSystemError(AuraError):
    """Base class for all Voice System errors."""


class MicrophoneError(VoiceSystemError):
    """Microphone unavailable, disconnected, or failed to open."""


class STTError(VoiceSystemError):
    """Speech-to-text backend failure (model load or transcription)."""


class WakeWordError(VoiceSystemError):
    """Wake-word backend failure."""


class NoSpeechDetected(VoiceSystemError):
    """A recording window elapsed without any speech."""


class LanguageDetectionError(VoiceSystemError):
    """Language detection failed (recovered by falling back to default)."""
