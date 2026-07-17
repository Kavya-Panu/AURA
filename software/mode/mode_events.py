"""
mode/mode_events.py
===================
Mapping between the Mode System's readable event names and the core
:class:`RobotEvent` bus vocabulary. Like the behavior layer, the Mode System
does not invent a parallel event bus - it publishes onto the existing one.
"""
from __future__ import annotations

from enum import Enum

from core.constants import RobotEvent
from .mode_types import ModeType


class ModeEvent(Enum):
    """Lifecycle events emitted for every mode transition."""
    ENTERING = RobotEvent.MODE_ENTERING
    ENTERED = RobotEvent.MODE_ENTERED
    EXITING = RobotEvent.MODE_EXITING
    EXITED = RobotEvent.MODE_EXITED
    CHANGED = RobotEvent.MODE_CHANGED
    FAILED = RobotEvent.MODE_FAILED


#: The event other modules publish to REQUEST a mode change (decoupled entry).
MODE_REQUEST_EVENT: RobotEvent = RobotEvent.MODE_REQUESTED

#: Optional per-mode "started" events that hardware/behavior modules subscribe
#: to. Modes not listed simply rely on the generic MODE_ENTERED event.
MODE_ENTRY_EVENT: dict[ModeType, RobotEvent] = {
    ModeType.FOCUS:       RobotEvent.FOCUS_MODE_STARTED,
    ModeType.TRANSLATION: RobotEvent.TRANSLATION_MODE_STARTED,
    ModeType.NIGHT:       RobotEvent.NIGHT_MODE_STARTED,
    ModeType.CHARGING:    RobotEvent.CHARGING_MODE_STARTED,
}
