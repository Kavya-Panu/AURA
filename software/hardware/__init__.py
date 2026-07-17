"""
hardware - AURA's Hardware Abstraction Layer (HAL).

The ONLY module that communicates with physical hardware. It owns the ESP32
serial link and a registry of devices (servo, speaker, display, propeller, LED,
battery, camera, microphone, ...), and exposes a single command API plus Event
Bus integration. No other module touches a port, servo, LED, propeller, or
sensor.

Runs on a laptop with no hardware by injecting mock backends:

    from hardware import HardwareManager, HardwareConfig
    from hardware.serial_manager import MockSerialTransport
    hal = HardwareManager(bus, HardwareConfig(), MockSerialTransport())
    lifecycle.register(hal)                     # it is a core Module
    hal.set_emotion("HAPPY")                    # forwarded to the ESP32 face
"""
from .device_registry import (
    Device, DeviceRegistry, MockDevice, SerialDevice,
)
from .device_types import (
    CommandPriority, ConnectionState, DeviceType, HealthState,
)
from .hardware_config import (
    HardwareConfig, HealthConfig, QueueConfig, SerialConfig,
)
from .hardware_manager import HardwareManager
from .serial_manager import (
    MockSerialTransport, PySerialTransport, SerialManager, SerialTransport,
)

__all__ = [
    "HardwareManager", "HardwareConfig", "SerialConfig", "QueueConfig",
    "HealthConfig", "SerialManager", "SerialTransport", "MockSerialTransport",
    "PySerialTransport", "DeviceRegistry", "Device", "SerialDevice",
    "MockDevice", "DeviceType", "ConnectionState", "HealthState",
    "CommandPriority",
]

# --- Hardware Stage 2: drivers, router, context ---
from .face_driver import FaceDriver, CommandSink, MockCommandSink
from .servo_driver import ServoDriver, ServoLimits
from .led_driver import LedDriver, Color
from .propeller_driver import PropellerDriver
from .battery_monitor import BatteryMonitor, BatteryStatus, ChargeState
from .command_router import CommandRouter, HardwareCommand, CommandStatus
from .hardware_context import HardwareContext, HardwareSnapshot

__all__ += [
    "FaceDriver", "CommandSink", "MockCommandSink", "ServoDriver", "ServoLimits",
    "LedDriver", "Color", "PropellerDriver", "BatteryMonitor", "BatteryStatus",
    "ChargeState", "CommandRouter", "HardwareCommand", "CommandStatus",
    "HardwareContext", "HardwareSnapshot",
]
