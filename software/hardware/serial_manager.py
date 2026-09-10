"""
hardware/serial_manager.py
==========================
The SerialManager owns the ESP32 serial link: it connects (auto-detecting the
port), sends commands from a thread-safe priority queue on a dedicated writer
thread, reads responses on a reader thread, auto-reconnects on disconnect, and
enforces timeouts.

The transport itself is behind a SerialTransport Protocol (dependency injection):
    * PySerialTransport - real; lazily imports `pyserial`.
    * MockSerialTransport - in-process fake with a scripted/echo responder, so the
      whole robot runs on a laptop with no hardware.

The SerialManager is transport-agnostic; only the injected transport touches a
physical port.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from core.event_bus import EventBus
from core.logger import get_logger

from . import hardware_events as ev
from .device_types import CommandPriority, ConnectionState
from .hardware_config import SerialConfig
from .hardware_exceptions import NotConnected, SerialError

log = get_logger("hardware.serial")


@runtime_checkable
class SerialTransport(Protocol):
    """Minimal serial transport. Real impl wraps pyserial; mock is in-process."""
    def open(self, port: str, baud: int, read_timeout_s: float,
             write_timeout_s: float) -> None: ...
    def close(self) -> None: ...
    def is_open(self) -> bool: ...
    def write_line(self, line: str) -> None: ...
    def read_line(self) -> str | None: ...           # None if nothing available
    @staticmethod
    def list_ports() -> list[str]: ...


class MockSerialTransport:
    """In-process fake transport. `responder(line) -> list[str]` produces the
    lines the device would send back (default: an ACK echo). Supports simulated
    disconnects for reconnect testing."""

    def __init__(self,
                 responder: Callable[[str], list[str]] | None = None,
                 ports: list[str] | None = None) -> None:
        self._responder = responder or (lambda line: [f"ACK {line}"])
        self._ports = ports if ports is not None else ["MOCK0"]
        self._open = False
        self._lock = threading.RLock()
        self._rx: list[str] = []
        self.written: list[str] = []
        self._fail_open = False

    # test hooks
    def set_ports(self, ports: list[str]) -> None:
        self._ports = list(ports)

    def simulate_disconnect(self) -> None:
        with self._lock:
            self._open = False

    def set_fail_open(self, fail: bool) -> None:
        self._fail_open = fail

    def push_incoming(self, line: str) -> None:
        with self._lock:
            self._rx.append(line)

    # transport interface
    def open(self, port: str, baud: int, read_timeout_s: float,
             write_timeout_s: float) -> None:
        if self._fail_open:
            raise SerialError(f"mock: cannot open {port}")
        with self._lock:
            self._open = True

    def close(self) -> None:
        with self._lock:
            self._open = False

    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def write_line(self, line: str) -> None:
        with self._lock:
            if not self._open:
                raise SerialError("mock: not open")
            self.written.append(line)
            self._rx.extend(self._responder(line))

    def read_line(self) -> str | None:
        with self._lock:
            if not self._open:
                return None
            return self._rx.pop(0) if self._rx else None

    def list_ports(self) -> list[str]:
        return list(self._ports)


class PySerialTransport:
    """Real transport via pyserial (lazily imported)."""

    def __init__(self) -> None:
        self._serial = None
        self._rx_buffer = bytearray()
        self._discard_rx_line = False

    def open(self, port: str, baud: int, read_timeout_s: float,
             write_timeout_s: float) -> None:
        try:
            import serial                              # lazy import (pyserial)
        except Exception as exc:                        # noqa: BLE001
            raise SerialError(f"pyserial not available: {exc}") from exc
        try:
            self._rx_buffer.clear()
            self._discard_rx_line = False
            self._serial = serial.Serial(
                port=port, baudrate=baud, timeout=read_timeout_s,
                write_timeout=write_timeout_s)
        except Exception as exc:                        # noqa: BLE001
            raise SerialError(f"cannot open {port}: {exc}") from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None
                self._rx_buffer.clear()
                self._discard_rx_line = False

    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def write_line(self, line: str) -> None:
        if self._serial is None:
            raise SerialError("serial not open")
        try:
            self._serial.write((line + "\n").encode("utf-8"))
        except Exception as exc:                        # noqa: BLE001
            raise SerialError(f"write failed: {exc}") from exc

    def read_line(self) -> str | None:
        if self._serial is None:
            return None
        try:
            if b"\n" not in self._rx_buffer:
                # Read USB packets in batches. pyserial.readline() reads one
                # byte at a time and may return a partial line on timeout;
                # treating that fragment as a complete MIC packet loses audio.
                waiting = self._serial.in_waiting
                raw = self._serial.read(max(1, min(waiting, 4096)))
                if self._discard_rx_line:
                    newline = raw.find(b"\n")
                    if newline < 0:
                        return None
                    raw = raw[newline + 1:]
                    self._discard_rx_line = False
                self._rx_buffer.extend(raw)
            newline = self._rx_buffer.find(b"\n")
            if newline < 0:
                if len(self._rx_buffer) > 16384:
                    self._rx_buffer.clear()
                    self._discard_rx_line = True
                return None
            raw = bytes(self._rx_buffer[:newline])
            del self._rx_buffer[:newline + 1]
        except Exception as exc:                        # noqa: BLE001
            raise SerialError(f"read failed: {exc}") from exc
        if not raw:
            return None
        return raw.decode("utf-8", errors="replace").strip()

    @staticmethod
    def list_ports() -> list[str]:
        try:
            from serial.tools import list_ports         # lazy import
            return [p.device for p in list_ports.comports()]
        except Exception:                               # noqa: BLE001
            return []


@dataclass(order=True)
class _QueuedCommand:
    priority: int
    sequence: int
    line: str = field(compare=False)


class SerialManager:
    """Manages the ESP32 serial link with queueing, reader/writer threads and
    auto-reconnect. Thread-safe."""

    def __init__(self, event_bus: EventBus, config: SerialConfig,
                 transport: SerialTransport,
                 on_line: Callable[[str], bool | None] | None = None,
                 queue_max: int = 256,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._cfg = config
        self._transport = transport
        self._on_line = on_line
        self._clock = clock

        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.RLock()

        self._heap: list[_QueuedCommand] = []
        self._counter = itertools.count()
        self._queue_max = queue_max
        self._queue_cv = threading.Condition()

        self._running = threading.Event()
        self._writer: threading.Thread | None = None
        self._reader: threading.Thread | None = None
        self._port: str | None = None
        # Keeps large real-time audio writes and ordinary command writes from
        # interleaving on the same UART.
        self._io_write_lock = threading.RLock()
        # Microphone and speaker handshakes must briefly own the serial link.
        # Otherwise queued gaze/emotion commands can surround SPK BEGIN or
        # MIC START and delay the matching firmware reply long enough for the
        # audio operation to time out.
        self._queued_writes_paused = threading.Event()
        self._audio_priority_allowed = threading.Event()

    # ------------------------------------------------------------- state
    @property
    def state(self) -> ConnectionState:
        with self._state_lock:
            return self._state

    @property
    def connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    def _set_state(self, state: ConnectionState) -> None:
        with self._state_lock:
            self._state = state

    # ------------------------------------------------------- discovery
    def list_ports(self) -> list[str]:
        return self._transport.list_ports()

    def _pick_port(self) -> str | None:
        if self._cfg.port:
            return self._cfg.port
        ports = self._transport.list_ports()
        for p in ports:
            if any(h.lower() in p.lower() for h in self._cfg.port_hints):
                return p
        return ports[0] if ports else None

    # ---------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._connect()
        self._writer = threading.Thread(target=self._writer_loop,
                                        name="serial-writer", daemon=True)
        self._reader = threading.Thread(target=self._reader_loop,
                                        name="serial-reader", daemon=True)
        self._writer.start()
        self._reader.start()

    def stop(self) -> None:
        self._running.clear()
        with self._queue_cv:
            self._queue_cv.notify_all()
        for t in (self._writer, self._reader):
            if t is not None:
                t.join(timeout=2.0)
        self._writer = self._reader = None
        try:
            self._transport.close()
        finally:
            self._set_state(ConnectionState.DISCONNECTED)
            self._bus.emit(ev.SERIAL_DISCONNECTED, {"port": self._port},
                           source="hardware.serial")

    def _connect(self) -> bool:
        self._set_state(ConnectionState.CONNECTING)
        port = self._pick_port()
        if port is None:
            self._set_state(ConnectionState.ERROR)
            return False
        try:
            self._transport.open(port, self._cfg.baud_rate,
                                 self._cfg.read_timeout_s, self._cfg.write_timeout_s)
        except SerialError as exc:
            log.warning("serial connect failed: %s", exc)
            self._set_state(ConnectionState.ERROR)
            return False
        self._port = port
        self._set_state(ConnectionState.CONNECTED)
        self._bus.emit(ev.SERIAL_CONNECTED, {"port": port},
                       source="hardware.serial")
        log.info("serial connected on %s", port)
        return True

    # ------------------------------------------------------------- queue
    def send(self, line: str,
             priority: CommandPriority = CommandPriority.NORMAL) -> bool:
        """Queue a command line. Returns False if the queue is full."""
        with self._queue_cv:
            # Camera targets can change throughout a long wake-listening
            # session. Only the latest target matters when audio releases the
            # queue; replaying hundreds of old gaze/head positions causes lag.
            key = self._target_key(line)
            # Head tracking must continue during the long wake-microphone
            # stream. Promote only this coalesced target, not all camera
            # traffic. The audio handshake gate still blocks every queued
            # command until it is safe to interleave complete lines.
            if key == "head":
                priority = min(priority, CommandPriority.HIGH)
            if key:
                self._heap = [item for item in self._heap
                              if self._target_key(item.line) != key]
                heapq.heapify(self._heap)
            if len(self._heap) >= self._queue_max:
                return False
            heapq.heappush(self._heap,
                           _QueuedCommand(int(priority), next(self._counter), line))
            self._queue_cv.notify()
            return True

    @staticmethod
    def _target_key(line: str) -> str:
        if line.startswith(("GAZE ", "LOOK ")):
            return "gaze"
        if line.startswith("SERVO:HEAD:"):
            return "head"
        if line.startswith("MUSIC LEVEL "):
            return "music_level"
        return ""

    def send_immediate(self, line: str) -> bool:
        """Write one line synchronously.

        Audio frames use this path so their order cannot be changed by command
        priorities. Normal face/control commands should continue using send().
        """
        try:
            if not self._transport.is_open():
                raise NotConnected("serial not open")
            with self._io_write_lock:
                self._transport.write_line(line)
            return True
        except (SerialError, NotConnected) as exc:
            log.warning("immediate write failed (%s)", exc)
            self._handle_disconnect()
            return False

    def pause_queued_writes(self) -> None:
        """Pause ordinary queued commands while real-time audio owns UART.

        Immediate audio writes intentionally bypass this gate.  Taking and
        releasing the write lock after setting the flag also waits for any
        ordinary command that was already being written to finish.
        """
        self._queued_writes_paused.set()
        self._audio_priority_allowed.clear()
        with self._io_write_lock:
            pass

    def resume_queued_writes(self) -> None:
        """Allow queued face, servo and heartbeat commands to continue."""
        self._queued_writes_paused.clear()
        self._audio_priority_allowed.clear()
        with self._queue_cv:
            self._queue_cv.notify_all()

    def resume_priority_commands(self) -> None:
        """After an audio handshake, allow sparse scene/emotion updates.

        LOW/NORMAL gaze and heartbeat traffic stays queued. HIGH/CRITICAL
        updates, including coalesced head targets and TIMER STOP, must not
        wait for the next wake phrase.
        The write lock still keeps each command and PCM packet intact.
        """
        self._audio_priority_allowed.set()
        with self._queue_cv:
            self._queue_cv.notify_all()

    def _command_blocked(self, command: _QueuedCommand) -> bool:
        return self._queued_writes_paused.is_set() and (
            not self._audio_priority_allowed.is_set()
            or command.priority > int(CommandPriority.HIGH)
        )

    def _writer_loop(self) -> None:
        while self._running.is_set():
            with self._queue_cv:
                while self._running.is_set() and (
                    not self._heap or self._command_blocked(self._heap[0])
                ):
                    self._queue_cv.wait(timeout=0.2)
                if not self._running.is_set():
                    break
                cmd = heapq.heappop(self._heap) if self._heap else None
            if cmd is None:
                continue
            # If an audio handshake began after popping this command, put it
            # back. Waiting on a popped LOW command would block later HIGH
            # commands even when they are allowed during the audio stream.
            with self._io_write_lock:
                if self._command_blocked(cmd):
                    with self._queue_cv:
                        heapq.heappush(self._heap, cmd)
                    continue
                if not self._running.is_set():
                    break
                self._write_with_recovery(cmd.line)

    def _write_with_recovery(self, line: str) -> None:
        try:
            if not self._transport.is_open():
                raise NotConnected("serial not open")
            with self._io_write_lock:
                self._transport.write_line(line)
            self._bus.emit(ev.COMMAND_SENT, {"line": line},
                           source="hardware.serial")
            if self._cfg and getattr(self._cfg, "port", None) is not None:
                pass
        except (SerialError, NotConnected) as exc:
            log.warning("write failed (%s); triggering reconnect", exc)
            self._handle_disconnect()

    # ------------------------------------------------------------ reader
    def _reader_loop(self) -> None:
        while self._running.is_set():
            try:
                line = self._transport.read_line() if self._transport.is_open() else None
            except SerialError as exc:
                log.warning("read failed (%s); triggering reconnect", exc)
                self._handle_disconnect()
                continue
            if line is None:
                if not self._transport.is_open() and self._running.is_set():
                    self._handle_disconnect()
                    continue
                time.sleep(0.005)
                continue
            consumed = False
            if self._on_line is not None:
                try:
                    consumed = bool(self._on_line(line))
                except Exception:                       # noqa: BLE001
                    log.exception("on_line handler failed")
            # PCM lines arrive 50 times per second. They are routed directly to
            # the audio queue instead of flooding the global EventBus/logs.
            if not consumed:
                self._bus.emit(ev.COMMAND_RECEIVED, {"line": line},
                               source="hardware.serial")

    # -------------------------------------------------------- reconnect
    def _handle_disconnect(self) -> None:
        # Reconnect only applies to losing an ESTABLISHED link. If we never
        # connected (ERROR) or are already reconnecting, do nothing - this keeps
        # a failed initial connect in ERROR instead of spinning a reconnect loop.
        if self.state != ConnectionState.CONNECTED:
            return
        self._set_state(ConnectionState.RECONNECTING)
        self._bus.emit(ev.SERIAL_DISCONNECTED, {"port": self._port},
                       source="hardware.serial")
        try:
            self._transport.close()
        except Exception:                               # noqa: BLE001
            pass
        attempts = 0
        while self._running.is_set():
            attempts += 1
            time.sleep(self._cfg.reconnect_delay_s)
            if not self._running.is_set():
                return
            if self._connect():
                return
            if (self._cfg.max_reconnect_attempts and
                    attempts >= self._cfg.max_reconnect_attempts):
                log.error("giving up serial reconnect after %d attempts", attempts)
                self._set_state(ConnectionState.ERROR)
                return

    def force_reconnect(self) -> None:
        """Public hook used by tests / health monitor to recover a dead link."""
        self._handle_disconnect()
