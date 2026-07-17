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
    QUESTION_RECEIVED = auto()
    ANSWER_READY = auto()
    VOICE_ERROR = auto()

    # --- behaviors (future) ---
    FOCUS_STARTED = auto()
    FOCUS_FINISHED = auto()
    FOCUS_ABORTED = auto()
    EMOTION_CHANGED = auto()
    USER_GREETING = auto()
    BREAK_STARTED = auto()
    BREAK_FINISHED = auto()
    BATTERY_OK = auto()
    CAMERA_ERROR = auto()

    # --- modes ---
    MODE_REQUESTED = auto()
    MODE_ENTERING = auto()
    MODE_ENTERED = auto()
    MODE_EXITING = auto()
    MODE_EXITED = auto()
    MODE_CHANGED = auto()
    MODE_FAILED = auto()
    FOCUS_MODE_STARTED = auto()
    TRANSLATION_MODE_STARTED = auto()
    NIGHT_MODE_STARTED = auto()
    CHARGING_MODE_STARTED = auto()

    # --- voice ---
    VOICE_STARTED = auto()
    VOICE_STOPPED = auto()
    WAKE_WORD_DETECTED = auto()
    TEXT_RECOGNIZED = auto()
    MICROPHONE_ERROR = auto()
    LANGUAGE_DETECTED = auto()
    NO_SPEECH_DETECTED = auto()

    # --- vision (stage 1: lifecycle + camera; detection events reuse those above) ---
    VISION_STARTED = auto()
    VISION_STOPPED = auto()
    CAMERA_CONNECTED = auto()
    CAMERA_DISCONNECTED = auto()
    VISION_ERROR = auto()
    VISION_RESULT = auto()
    FACE_TRACKED = auto()
    FACE_POSITION = auto()
    PERSON_FOUND = auto()
    PHONE_DURATION_UPDATED = auto()

    # --- vision stages 3-final: interaction detectors + pipeline ---
    HAND_WAVE = auto()
    HAND_RAISED = auto()
    THUMBS_UP = auto()
    USER_SMILING = auto()
    USER_NOT_SMILING = auto()
    LOOKING_AT_ROBOT = auto()
    LOOKING_AWAY = auto()
    HEAD_LEFT = auto()
    HEAD_RIGHT = auto()
    HEAD_UP = auto()
    HEAD_DOWN = auto()
    HEAD_CENTER = auto()
    USER_TIRED = auto()
    PIPELINE_STARTED = auto()
    PIPELINE_STOPPED = auto()
    PIPELINE_ERROR = auto()

    # --- brain (intelligence layer) ---
    BRAIN_REQUESTED = auto()
    BRAIN_STARTED = auto()
    BRAIN_COMPLETED = auto()
    BRAIN_FAILED = auto()
    TRANSLATION_STARTED = auto()
    TRANSLATION_COMPLETED = auto()
    PROVIDER_CHANGED = auto()

    # --- speech (expression layer) ---
    SPEECH_CANCELLED = auto()
    VOICE_CHANGED = auto()
    TTS_STARTED = auto()
    TTS_FINISHED = auto()
    EXPRESSION_CHANGED = auto()
    MOUTH_ANIMATION_STARTED = auto()
    MOUTH_ANIMATION_STOPPED = auto()

    # --- memory (persistence layer) ---
    MEMORY_STORED = auto()
    MEMORY_RETRIEVED = auto()
    MEMORY_UPDATED = auto()
    MEMORY_DELETED = auto()
    MEMORY_SEARCHED = auto()
    MEMORY_SUMMARIZED = auto()
    MEMORY_FORGOTTEN = auto()
    MEMORY_EXPIRED = auto()
    MEMORY_CLEANUP_COMPLETED = auto()


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
