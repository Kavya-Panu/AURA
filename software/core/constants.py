"""
core/constants.py
=================
Single source of truth for every enum and constant in AURA.

Nothing anywhere else in the codebase should define states, event names,
emotions or command strings - they all live here so that modules can never
drift out of sync with each other.
"""
from __future__ import annotations

from enum import Enum, auto

VERSION: str = "0.1.0"
ROBOT_NAME: str = "AURA"


class RobotState(Enum):
    """Top-level operating states of the robot (used by the StateMachine)."""
    BOOTING = auto()
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    ANSWERING = auto()
    FOCUS = auto()
    BREAK = auto()
    SEARCHING = auto()
    SLEEPING = auto()
    SHUTDOWN = auto()


class RobotEvent(Enum):
    """Every event type that can travel on the EventBus.

    Future modules add their events HERE first, then publish them.
    """
    # --- lifecycle / system ---
    STARTUP_COMPLETE = auto()
    SHUTDOWN_STARTED = auto()
    MODULE_STARTED = auto()
    MODULE_STOPPED = auto()
    MODULE_FAILED = auto()
    HEALTH_REPORT = auto()
    STATE_CHANGED = auto()
    TIMER_EXPIRED = auto()
    BATTERY_LOW = auto()

    # --- vision (future) ---
    FACE_FOUND = auto()
    FACE_LOST = auto()
    PHONE_DETECTED = auto()
    PHONE_GONE = auto()
    PERSON_LEFT = auto()
    PERSON_RETURNED = auto()

    # --- voice / AI (future) ---
    WAKE_WORD = auto()
    VOICE_COMMAND = auto()
    LLM_RESPONSE = auto()
    SPEECH_STARTED = auto()
    SPEECH_FINISHED = auto()

    # --- behaviors (future) ---
    FOCUS_STARTED = auto()
    FOCUS_FINISHED = auto()
    FOCUS_ABORTED = auto()
    EMOTION_CHANGED = auto()


class Emotion(Enum):
    """Emotions AURA can express. Values are the ESP32 serial tokens, so a
    future FaceLink module can send ``emotion.value`` directly."""
    NORMAL = "NORMAL"
    HAPPY = "HAPPY"
    EXCITED = "EXCITED"
    SAD = "SAD"
    ANGRY = "ANGRY"
    SURPRISED = "SURPRISED"
    CONFUSED = "CONFUSED"
    CURIOUS = "CURIOUS"
    LOVE = "LOVE"
    THINKING = "THINK"
    LISTENING = "LISTEN"
    SEARCHING = "SEARCH"
    WORRIED = "WORRIED"
    CELEBRATE = "CELEBRATE"
    SLEEPY = "SLEEPY"
    SLEEP = "SLEEP"
    ERROR = "ERROR"


class FaceCommand(Enum):
    """Non-emotion commands understood by the ESP32 face engine."""
    FOCUS_START = "FOCUS_START"
    FOCUS_DONE = "FOCUS_DONE"
    FOCUS_STOP = "FOCUS_STOP"
    PROGRESS = "PROGRESS"          # "PROGRESS 0.42"
    TALK_ON = "TALK_ON"
    TALK_OFF = "TALK_OFF"
    GAZE = "GAZE"                  # "GAZE 0.30 -0.10"
    CENTER = "CENTER"
    BLINK = "BLINK"
    WINK = "WINK"
    SLEEP = "SLEEP"
    WAKE = "WAKE"
    BOOT = "BOOT"
    SHUTDOWN = "SHUTDOWN"
    BATTERY_LOW = "BATTERY_LOW"
    CHARGING = "CHARGING"


class HardwareType(Enum):
    """Physical subsystems, used for health reports and HardwareError context."""
    FACE_DISPLAY = auto()
    CAMERA = auto()
    MICROPHONE = auto()
    SPEAKER = auto()
    NECK_SERVO = auto()
    PROPELLER = auto()
    LED = auto()
    SENSOR = auto()
