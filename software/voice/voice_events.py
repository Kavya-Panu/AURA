"""
voice/voice_events.py
=====================
Mapping of Voice System events to the core RobotEvent bus vocabulary. The Voice
System publishes ONLY these; the Intent Engine (and others) subscribe. No
parallel event system.
"""
from __future__ import annotations

from core.constants import RobotEvent

VOICE_STARTED = RobotEvent.VOICE_STARTED
VOICE_STOPPED = RobotEvent.VOICE_STOPPED
WAKE_WORD_DETECTED = RobotEvent.WAKE_WORD_DETECTED
SPEECH_STARTED = RobotEvent.SPEECH_STARTED
SPEECH_FINISHED = RobotEvent.SPEECH_FINISHED
TEXT_RECOGNIZED = RobotEvent.TEXT_RECOGNIZED
MICROPHONE_ERROR = RobotEvent.MICROPHONE_ERROR
LANGUAGE_DETECTED = RobotEvent.LANGUAGE_DETECTED
NO_SPEECH_DETECTED = RobotEvent.NO_SPEECH_DETECTED
