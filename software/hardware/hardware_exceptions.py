"""
hardware/hardware_exceptions.py
===============================
Hardware-layer exceptions, rooted in the project's AuraError.
"""
from __future__ import annotations

from core.exceptions import AuraError


class HardwareError(AuraError):
    """Base class for all Hardware Abstraction Layer errors."""


class SerialError(HardwareError):
    """A serial transport operation failed."""


class SerialTimeout(SerialError):
    """A serial read/write exceeded its timeout."""


class NotConnected(HardwareError):
    """An operation required a connection that isn't established."""


class DeviceError(HardwareError):
    """A device failed to operate."""


class DeviceNotFound(HardwareError):
    """No device is registered under the given name."""


class CommandError(HardwareError):
    """A command could not be built or sent."""
