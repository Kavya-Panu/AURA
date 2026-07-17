"""
hardware/hardware_config.py
===========================
Configuration for the Hardware Abstraction Layer. Pure data (dataclasses); no
magic numbers elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SerialConfig:
    """Serial transport settings for the ESP32 link."""
    port: str | None = None            # None => auto-detect
    baud_rate: int = 115200
    read_timeout_s: float = 0.2
    write_timeout_s: float = 1.0
    reconnect_delay_s: float = 2.0
    max_reconnect_attempts: int = 0    # 0 = retry forever
    # substrings used to auto-pick a likely ESP32 port during discovery
    port_hints: tuple[str, ...] = ("USB", "ACM", "SLAB", "CP210", "CH340", "wchusb")


@dataclass
class QueueConfig:
    """Outgoing command queue settings."""
    max_size: int = 256
    send_timeout_s: float = 1.0


@dataclass
class HealthConfig:
    """Heartbeat / health monitoring."""
    enabled: bool = True
    interval_s: float = 5.0
    heartbeat_command: str = "PING"
    battery_low_threshold: float = 20.0   # percent


@dataclass
class HardwareConfig:
    """Top-level HAL configuration."""
    serial: SerialConfig = field(default_factory=SerialConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    log_traffic: bool = False          # log every serial line (verbose)
