"""
mode/mode_registry.py
=====================
Registry mapping each :class:`ModeType` to its :class:`ModeDefinition` (default
params factory, optional per-mode "started" event, description). Adding a new
mode is one enum member + one ``registry.register(ModeDefinition(...))`` call;
the manager needs no changes.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from core.constants import RobotEvent
from core.logger import get_logger

from .mode_events import MODE_ENTRY_EVENT
from .mode_types import (
    ModeParams,
    ModeType,
    make_default_params,
)

log = get_logger("mode.registry")


@dataclass(frozen=True)
class ModeDefinition:
    """Static description of a mode."""
    mode: ModeType
    default_params_factory: Callable[[], ModeParams]
    entry_event: RobotEvent | None = None
    description: str = ""


class ModeRegistry:
    """Thread-safe ModeType -> ModeDefinition registry."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._defs: dict[ModeType, ModeDefinition] = {}

    def register(self, definition: ModeDefinition) -> None:
        with self._lock:
            if definition.mode in self._defs:
                raise ValueError(f"{definition.mode.name} already registered")
            self._defs[definition.mode] = definition
        log.debug("registered mode %s", definition.mode.name)

    def get(self, mode: ModeType) -> ModeDefinition:
        with self._lock:
            if mode not in self._defs:
                raise KeyError(f"Mode {mode.name} is not registered")
            return self._defs[mode]

    def is_registered(self, mode: ModeType) -> bool:
        with self._lock:
            return mode in self._defs

    def all_modes(self) -> list[ModeType]:
        with self._lock:
            return list(self._defs)


_DESCRIPTIONS: dict[ModeType, str] = {
    ModeType.NORMAL:       "Default interactive robot.",
    ModeType.FOCUS:        "Study-focus session with phone detection.",
    ModeType.TRANSLATION:  "Continuous two-way live translation.",
    ModeType.TEACHER:      "Guided lessons on a subject.",
    ModeType.QUIZ:         "Interactive quizzing.",
    ModeType.HOMEWORK:     "Assignment tracking and help.",
    ModeType.PRESENTATION: "Slide-driven presentation companion.",
    ModeType.ASSISTANT:    "Everyday assistant.",
    ModeType.MEMORY:       "Recall / notes mode.",
    ModeType.NIGHT:        "Quiet, dimmed, sleep behaviour.",
    ModeType.CHARGING:     "Charging animation and battery monitoring.",
    ModeType.MAINTENANCE:  "Diagnostics / servicing.",
}


def build_default_registry() -> ModeRegistry:
    """Registry pre-populated with all twelve modes."""
    reg = ModeRegistry()
    for mode in ModeType:
        reg.register(ModeDefinition(
            mode=mode,
            default_params_factory=lambda m=mode: make_default_params(m),
            entry_event=MODE_ENTRY_EVENT.get(mode),
            description=_DESCRIPTIONS.get(mode, ""),
        ))
    return reg


#: Shared default registry.
registry = build_default_registry()
