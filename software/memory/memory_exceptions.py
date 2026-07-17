"""
memory/memory_exceptions.py
===========================
Memory-layer exceptions, rooted in the project's AuraError.
"""
from __future__ import annotations

from core.exceptions import AuraError


class MemoryError_(AuraError):
    """Base class for all Memory Manager errors (trailing underscore avoids
    shadowing the builtin MemoryError)."""


class MemoryNotFound(MemoryError_):
    """No memory exists for the given id."""


class ProviderError(MemoryError_):
    """The storage provider failed."""


class MemoryValidationError(MemoryError_):
    """A memory record failed validation."""


class RetentionError(MemoryError_):
    """A retention/cleanup operation failed."""
