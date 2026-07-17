"""
hardware/device_types.py
========================
Enums describing hardware: device type, connection state, health state, and
command priority. New device kinds are added here (Open/Closed) without touching
the HardwareManager.
"""
from __future__ import annotations

from enum import Enum, IntEnum, auto


class DeviceType(Enum):
    """Kinds of hardware AURA can drive. Extend here to add new devices."""
    ESP32 = "esp32"                # the face engine controller (serial)
    SERVO = "servo"               # neck / pan-tilt
    SPEAKER = "speaker"
    DISPLAY = "display"           # the ILI9341 face display (driven via ESP32)
    PROPELLER = "propeller"
    LED = "led"
    BATTERY = "battery"
    CAMERA = "camera"
    MICROPHONE = "microphone"


class ConnectionState(Enum):
    """Lifecycle of a device/transport connection."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()
    ERROR = auto()


class HealthState(Enum):
    """Coarse health classification reported by a device."""
    UNKNOWN = auto()
    HEALTHY = auto()
    DEGRADED = auto()
    FAULT = auto()


class CommandPriority(IntEnum):
    """Priority for queued outgoing commands. LOWER value = sent sooner, so the
    queue is a min-heap on priority. Interrupts (e.g. emergency stop) use HIGH."""
    CRITICAL = 0        # emergency stop, safety
    HIGH = 10           # emotion changes, immediate expressions
    NORMAL = 50         # routine commands
    LOW = 90            # telemetry / non-urgent
