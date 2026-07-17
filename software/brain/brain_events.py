"""
brain/brain_events.py
=====================
Mapping of Brain events onto the core RobotEvent bus vocabulary. The Brain
publishes ONLY these; it also LISTENS to the existing QUESTION_RECEIVED event
(published by the Intent layer) and answers with ANSWER_READY, without inventing
a parallel event system.
"""
from __future__ import annotations

from core.constants import RobotEvent

# Brain lifecycle (added additively to core).
BRAIN_REQUESTED = RobotEvent.BRAIN_REQUESTED
BRAIN_STARTED = RobotEvent.BRAIN_STARTED
BRAIN_COMPLETED = RobotEvent.BRAIN_COMPLETED
BRAIN_FAILED = RobotEvent.BRAIN_FAILED
TRANSLATION_STARTED = RobotEvent.TRANSLATION_STARTED
TRANSLATION_COMPLETED = RobotEvent.TRANSLATION_COMPLETED
PROVIDER_CHANGED = RobotEvent.PROVIDER_CHANGED

# Existing events the Brain interoperates with (reused, not redefined).
QUESTION_RECEIVED = RobotEvent.QUESTION_RECEIVED     # Brain subscribes
ANSWER_READY = RobotEvent.ANSWER_READY               # Brain publishes the answer
