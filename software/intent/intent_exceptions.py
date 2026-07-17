"""
intent/intent_exceptions.py
===========================
Intent-Engine-specific exceptions, rooted in the project's AuraError so callers
can catch all AURA errors uniformly.
"""
from __future__ import annotations

from core.exceptions import AuraError


class IntentError(AuraError):
    """Base class for Intent Engine errors."""


class IntentParseError(IntentError):
    """Input text could not be parsed (empty/garbage after normalisation)."""


class IntentRegistryError(IntentError):
    """Registry misconfiguration (duplicate/unknown intent definitions)."""


class ParameterValidationError(IntentError):
    """A parameter failed validation and could not be repaired."""
