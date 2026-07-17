"""
brain/brain_exceptions.py
=========================
Brain-layer exceptions, rooted in the project's AuraError.
"""
from __future__ import annotations

from core.exceptions import AuraError


class BrainError(AuraError):
    """Base class for all Brain Manager errors."""


class ProviderError(BrainError):
    """A provider failed to generate a response."""


class ProviderUnavailable(ProviderError):
    """The selected provider is not available (offline, no client, no key)."""


class NoProviderAvailable(BrainError):
    """No provider could satisfy the request, even after fallback."""


class BrainTimeout(BrainError):
    """A generation exceeded its timeout."""


class BrainCancelled(BrainError):
    """A generation was cancelled by the caller."""


class TranslationError(BrainError):
    """Translation failed."""


class PromptError(BrainError):
    """A required prompt template was missing or invalid."""
