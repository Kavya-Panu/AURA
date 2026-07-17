"""
voice/microphone_manager.py
===========================
Owns the MicrophoneBackend lifecycle with automatic reconnection. Exposes a
blocking read_frame() that transparently retries across disconnects, and
reports microphone errors through an injected callback (the VoiceSystem turns
that into a bus event).
"""
from __future__ import annotations

import time
from typing import Callable

from core.logger import get_logger
from .backends import MicrophoneBackend
from .voice_config import MicrophoneConfig
from .voice_exceptions import MicrophoneError

log = get_logger("voice.mic")

ErrorCallback = Callable[[str], None]


class MicrophoneManager:
    def __init__(self, backend: MicrophoneBackend, cfg: MicrophoneConfig,
                 on_error: ErrorCallback | None = None,
                 sleep=time.sleep) -> None:
        self._backend = backend
        self._cfg = cfg
        self._on_error = on_error
        self._sleep = sleep
        self._attempts = 0

    def open(self) -> None:
        self._backend.open()
        self._attempts = 0

    def close(self) -> None:
        self._backend.close()

    def is_open(self) -> bool:
        return self._backend.is_open()

    def _reconnect(self) -> bool:
        """Try to reopen the mic. Returns True on success, False if attempts
        exhausted (max_reconnect_attempts == 0 means retry forever)."""
        self._attempts += 1
        if (self._cfg.max_reconnect_attempts
                and self._attempts > self._cfg.max_reconnect_attempts):
            return False
        if self._on_error is not None:
            self._on_error(f"microphone disconnected; reconnect attempt "
                           f"{self._attempts}")
        try:
            self._backend.close()
        except Exception:               # noqa: BLE001
            pass
        self._sleep(self._cfg.reconnect_interval_s)
        try:
            self._backend.open()
            log.info("microphone reconnected")
            return True
        except MicrophoneError:
            return True                 # keep trying on next read
        except Exception:               # noqa: BLE001
            return True

    def read_frame(self) -> bytes:
        """Blocking read with transparent reconnect. Raises MicrophoneError only
        when reconnection attempts are exhausted."""
        while True:
            try:
                return self._backend.read_frame()
            except MicrophoneError as exc:
                if not self._reconnect():
                    raise MicrophoneError("microphone permanently unavailable",
                                          {"attempts": self._attempts}) from exc
