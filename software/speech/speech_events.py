"""
speech/speech_events.py
=======================
Mapping of Speech events onto the core RobotEvent bus vocabulary. The Speech
Manager publishes ONLY these; it also LISTENS to ANSWER_READY (from the Brain)
so it can speak answers, and it sends emotions via the existing EMOTION_CHANGED
event (the same one the Behavior layer uses), which a FaceLink translates to
ESP32 tokens. No parallel event system.
"""
from __future__ import annotations

from core.constants import RobotEvent

# Speech lifecycle.
SPEECH_STARTED = RobotEvent.SPEECH_STARTED
SPEECH_FINISHED = RobotEvent.SPEECH_FINISHED
SPEECH_CANCELLED = RobotEvent.SPEECH_CANCELLED
VOICE_CHANGED = RobotEvent.VOICE_CHANGED
TTS_STARTED = RobotEvent.TTS_STARTED
TTS_FINISHED = RobotEvent.TTS_FINISHED
EXPRESSION_CHANGED = RobotEvent.EXPRESSION_CHANGED
MOUTH_ANIMATION_STARTED = RobotEvent.MOUTH_ANIMATION_STARTED
MOUTH_ANIMATION_STOPPED = RobotEvent.MOUTH_ANIMATION_STOPPED

# Existing events the Speech layer interoperates with (reused, not redefined).
ANSWER_READY = RobotEvent.ANSWER_READY          # Speech subscribes
EMOTION_CHANGED = RobotEvent.EMOTION_CHANGED    # Speech emits (face token)
