"""
hardware/hardware_events.py
===========================
Mapping of Hardware events onto the core RobotEvent bus vocabulary. The HAL
publishes these; it also SUBSCRIBES to EMOTION_CHANGED (emitted by the Speech and
Behavior layers) and forwards it to the ESP32 face - the HAL is the only module
that talks to hardware, so this is how software decisions reach the physical
face.
"""
from __future__ import annotations

from core.constants import RobotEvent

HARDWARE_STARTED = RobotEvent.HARDWARE_STARTED
HARDWARE_STOPPED = RobotEvent.HARDWARE_STOPPED
DEVICE_CONNECTED = RobotEvent.DEVICE_CONNECTED
DEVICE_DISCONNECTED = RobotEvent.DEVICE_DISCONNECTED
SERIAL_CONNECTED = RobotEvent.SERIAL_CONNECTED
SERIAL_DISCONNECTED = RobotEvent.SERIAL_DISCONNECTED
COMMAND_SENT = RobotEvent.COMMAND_SENT
COMMAND_RECEIVED = RobotEvent.COMMAND_RECEIVED
DEVICE_ERROR = RobotEvent.DEVICE_ERROR
BATTERY_LOW = RobotEvent.BATTERY_LOW              # reused (already in core)
HARDWARE_ERROR = RobotEvent.HARDWARE_ERROR

# Consumed (not redefined): the face-driving event emitted by Speech/Behavior.
EMOTION_CHANGED = RobotEvent.EMOTION_CHANGED
