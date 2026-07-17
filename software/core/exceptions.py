"""
core/exceptions.py
==================
Custom exception hierarchy. Every AURA error derives from :class:`AuraError`
so callers can catch "anything AURA-specific" with one except clause while
still being able to target precise failures.
"""
from __future__ import annotations

from typing import Any


class AuraError(Exception):
    """Base class for all AURA errors.

    Args:
        message: Human-readable description.
        context: Optional structured data (module name, device, values...)
            that gets appended to the message and is available to handlers.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        self.context: dict[str, Any] = context or {}
        if self.context:
            message = f"{message} | context={self.context}"
        super().__init__(message)


class ConfigurationError(AuraError):
    """Invalid, missing or unparseable configuration."""


class HardwareError(AuraError):
    """A physical device failed (display, servo, propeller, LED, sensor)."""


class VisionError(AuraError):
    """Camera or vision-pipeline failure (reserved for the vision module)."""


class VoiceError(AuraError):
    """Microphone, speech-to-text or text-to-speech failure (reserved)."""


class AIError(AuraError):
    """LLM provider failure: network, quota, bad response (reserved)."""


class CommunicationError(AuraError):
    """Inter-device link failure, e.g. the ESP32 serial connection."""


class StateTransitionError(AuraError):
    """An illegal state-machine transition was requested."""


class LifecycleError(AuraError):
    """A module failed to initialize, start or stop cleanly."""
