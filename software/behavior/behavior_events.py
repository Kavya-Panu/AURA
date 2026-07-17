"""
behavior/behavior_events.py
===========================
The perception-level triggers the Behavior System reacts to, and their mapping
onto the existing core :class:`RobotEvent` bus vocabulary.

Design choice: we do NOT invent a parallel event system. Most behavior triggers
already exist as ``RobotEvent`` values (PHONE_DETECTED, WAKE_WORD, FOCUS_STARTED
...). ``BehaviorTrigger`` is a readable alias layer, and ``TRIGGER_TO_EVENT``
maps each trigger to the core event the BehaviorManager subscribes to. A few
triggers that had no core event get new ones registered in ``EXTRA_EVENTS`` and
attached to ``RobotEvent`` at import time so nothing in core has to change.
"""
from __future__ import annotations

from enum import Enum, auto

from core.constants import RobotEvent


class BehaviorTrigger(Enum):
    """Human-readable triggers used when authoring behaviors/tests."""
    WAKE_WORD = auto()
    USER_GREETING = auto()
    QUESTION_RECEIVED = auto()
    ANSWER_READY = auto()
    FOCUS_STARTED = auto()
    FOCUS_FINISHED = auto()
    PHONE_DETECTED = auto()
    PHONE_REMOVED = auto()
    PERSON_FOUND = auto()
    PERSON_LOST = auto()
    BREAK_STARTED = auto()
    BREAK_FINISHED = auto()
    BATTERY_LOW = auto()
    BATTERY_OK = auto()
    CAMERA_ERROR = auto()
    VOICE_ERROR = auto()


# Trigger -> the core RobotEvent the BehaviorManager listens for.
# (All required events now live in core.constants.RobotEvent - see that file.)
TRIGGER_TO_EVENT: dict[BehaviorTrigger, RobotEvent] = {
    BehaviorTrigger.WAKE_WORD:         RobotEvent.WAKE_WORD,
    BehaviorTrigger.USER_GREETING:     RobotEvent.USER_GREETING,
    BehaviorTrigger.QUESTION_RECEIVED: RobotEvent.QUESTION_RECEIVED,
    BehaviorTrigger.ANSWER_READY:      RobotEvent.ANSWER_READY,
    BehaviorTrigger.FOCUS_STARTED:     RobotEvent.FOCUS_STARTED,
    BehaviorTrigger.FOCUS_FINISHED:    RobotEvent.FOCUS_FINISHED,
    BehaviorTrigger.PHONE_DETECTED:    RobotEvent.PHONE_DETECTED,
    BehaviorTrigger.PHONE_REMOVED:     RobotEvent.PHONE_GONE,
    BehaviorTrigger.PERSON_FOUND:      RobotEvent.PERSON_RETURNED,
    BehaviorTrigger.PERSON_LOST:       RobotEvent.PERSON_LEFT,
    BehaviorTrigger.BREAK_STARTED:     RobotEvent.BREAK_STARTED,
    BehaviorTrigger.BREAK_FINISHED:    RobotEvent.BREAK_FINISHED,
    BehaviorTrigger.BATTERY_LOW:       RobotEvent.BATTERY_LOW,
    BehaviorTrigger.BATTERY_OK:        RobotEvent.BATTERY_OK,
    BehaviorTrigger.CAMERA_ERROR:      RobotEvent.CAMERA_ERROR,
    BehaviorTrigger.VOICE_ERROR:       RobotEvent.VOICE_ERROR,
}

EVENT_TO_TRIGGER: dict[RobotEvent, BehaviorTrigger] = {
    ev: tr for tr, ev in TRIGGER_TO_EVENT.items()
}
