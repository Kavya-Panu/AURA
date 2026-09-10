"""Real-time audio bridge for the LCDWIKI ES3C28P onboard ES8311 codec."""
from __future__ import annotations

import base64
import queue
import threading
import time
from collections.abc import Callable

from core.logger import get_logger

from .serial_manager import SerialManager

log = get_logger("hardware.esp32_audio")


class Esp32AudioError(RuntimeError):
    pass


class Esp32AudioLink:
    """Multiplexes 16 kHz mono PCM over AURA's existing serial link.

    The ESP32 transports one 20 ms PCM frame per Base64 line. The link is
    ordinarily half duplex, but the firmware can keep RX active during speaker
    playback for a tiny local grammar containing only explicit stop commands.
    """

    sample_rate = 16_000
    frame_samples = 320
    frame_bytes = 640
    frame_duration_s = 0.020

    def __init__(self, serial: SerialManager) -> None:
        self._serial = serial
        self._mic_frames: queue.Queue[bytes] = queue.Queue(maxsize=1800)
        self._audio_ready = threading.Event()
        self._mic_started = threading.Event()
        self._mic_ended = threading.Event()
        self._speaker_ready = threading.Event()
        self._speaker_done = threading.Event()
        self._error_lock = threading.RLock()
        self._last_error = ""
        self._mode_lock = threading.RLock()
        # I2S/USB transfers can occasionally deliver fewer than 320 samples
        # in one MIC line.  Preserve every valid PCM byte and expose only
        # complete 20 ms frames to VAD/Whisper instead of discarding speech.
        self._mic_pcm_buffer = bytearray()
        self._mic_buffer_lock = threading.RLock()
        # USB serial is shared by face commands and real-time PCM audio.
        # Mark audio sessions so gaze/heartbeat traffic can pause while every
        # 20 ms microphone or speaker frame is in flight.
        self._mic_active = threading.Event()
        self._speaker_active = threading.Event()

    @property
    def ready(self) -> bool:
        return self._audio_ready.is_set()

    @property
    def busy(self) -> bool:
        """True while the ESP32 microphone or speaker owns the serial link."""
        return self._mic_active.is_set() or self._speaker_active.is_set()

    @property
    def microphone_active(self) -> bool:
        return self._mic_active.is_set()

    @property
    def speaker_active(self) -> bool:
        return self._speaker_active.is_set()

    @property
    def last_error(self) -> str:
        with self._error_lock:
            return self._last_error

    def handle_line(self, line: str) -> bool:
        """Consume audio protocol lines. Return True when handled."""
        if line.startswith("MIC:"):
            try:
                frame = base64.b64decode(line[4:], validate=True)
            except Exception:  # noqa: BLE001
                log.warning("discarded malformed microphone frame")
                return True
            if not frame:
                return True
            if len(frame) % 2:
                # PCM16 samples must contain two bytes.  A single trailing
                # byte cannot be decoded safely, but the rest is still useful.
                log.warning("trimmed odd byte from %d-byte microphone chunk",
                            len(frame))
                frame = frame[:-1]
            if not frame:
                return True
            with self._mic_buffer_lock:
                self._mic_pcm_buffer.extend(frame)
                while len(self._mic_pcm_buffer) >= self.frame_bytes:
                    complete = bytes(self._mic_pcm_buffer[:self.frame_bytes])
                    del self._mic_pcm_buffer[:self.frame_bytes]
                    self._queue_mic_frame(complete)
            return True

        if line.startswith("AUDIO READY"):
            self._audio_ready.set()
            return True
        if line.startswith("AUDIO ERROR"):
            with self._error_lock:
                self._last_error = line
            # Unblock any operation that is waiting for a reply.
            self._mic_started.set()
            self._speaker_ready.set()
            return True
        if line.startswith("MIC BEGIN"):
            self._mic_ended.clear()
            self._mic_started.set()
            return True
        if line == "MIC END":
            self._mic_ended.set()
            return True
        if line == "SPK READY":
            self._speaker_done.clear()
            self._speaker_ready.set()
            return True
        if line == "SPK DONE":
            self._speaker_done.set()
            return True
        return False

    def probe(self, timeout_s: float = 3.0) -> bool:
        self._pause_background_commands()
        try:
            self._audio_ready.clear()
            self._serial.send_immediate("AUDIO INFO")
            return self._audio_ready.wait(timeout_s)
        finally:
            self._resume_background_commands()

    def start_microphone(self, timeout_s: float = 2.0) -> None:
        with self._mode_lock:
            self._pause_background_commands()
            self._mic_active.set()
            self._clear_mic_queue()
            self._mic_started.clear()
            with self._error_lock:
                self._last_error = ""
            try:
                if not self._serial.send_immediate("MIC START"):
                    raise Esp32AudioError("could not send MIC START")
                if not self._mic_started.wait(timeout_s):
                    raise Esp32AudioError("ESP32 microphone did not start")
                if self.last_error:
                    raise Esp32AudioError(self.last_error)
                self._resume_background_commands()
            except Exception:
                self._mic_active.clear()
                self._resume_background_commands()
                raise

    def stop_microphone(self) -> None:
        with self._mode_lock:
            self._pause_background_commands()
            try:
                self._mic_ended.clear()
                self._serial.send_immediate("MIC STOP")
                self._mic_ended.wait(0.75)
            finally:
                self._mic_active.clear()
                self._resume_background_commands()

    def read_microphone_frame(self, timeout_s: float = 1.0) -> bytes:
        try:
            return self._mic_frames.get(timeout=timeout_s)
        except queue.Empty as exc:
            raise Esp32AudioError("microphone audio stream timed out") from exc

    def play_pcm(self, pcm: bytes, should_stop: Callable[[], bool]) -> bool:
        """Play signed int16 mono PCM, paced in real time."""
        if not pcm:
            return True
        if len(pcm) % 2:
            pcm = pcm[:-1]

        with self._mode_lock:
            self._pause_background_commands()
            self._speaker_active.set()
            self._speaker_ready.clear()
            self._speaker_done.clear()
            completed = False
            with self._error_lock:
                self._last_error = ""
            try:
                # Always restore the codec's persistent mute state before
                # switching from wake-word microphone capture to playback.
                # The direct hardware sweep proved this explicit command is
                # required on the ES3C28P/ES8311 after some capture sessions.
                if not self._serial.send_immediate("AUDIO UNMUTE"):
                    raise Esp32AudioError("could not unmute ESP32 speaker")
                time.sleep(0.03)
                if not self._serial.send_immediate("SPK BEGIN"):
                    raise Esp32AudioError("could not send SPK BEGIN")
                if not self._speaker_ready.wait(2.0):
                    raise Esp32AudioError("ESP32 speaker did not start")
                if self.last_error:
                    raise Esp32AudioError(self.last_error)

                self._resume_background_commands()
                deadline = time.monotonic()
                completed = True
                for offset in range(0, len(pcm), self.frame_bytes):
                    if should_stop():
                        completed = False
                        break
                    frame = pcm[offset:offset + self.frame_bytes]
                    if len(frame) < self.frame_bytes:
                        frame += b"\x00" * (self.frame_bytes - len(frame))
                    payload = base64.b64encode(frame).decode("ascii")
                    if not self._serial.send_immediate("SPK:" + payload):
                        raise Esp32AudioError("speaker stream disconnected")

                    # Pacing avoids overflowing ESP32 UART/I2S buffers.
                    deadline += self.frame_duration_s
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                return completed
            finally:
                self._pause_background_commands()
                self._serial.send_immediate(
                    "SPK END" if completed else "SPK ABORT"
                )
                self._speaker_done.wait(1.5)
                self._speaker_active.clear()
                self._resume_background_commands()

    def start_speaker_stream(self, timeout_s: float = 2.0) -> None:
        """Open a paced live speaker session used by the music relay."""
        with self._mode_lock:
            if self._speaker_active.is_set():
                return
            self._pause_background_commands()
            self._speaker_active.set()
            self._speaker_ready.clear()
            self._speaker_done.clear()
            with self._error_lock:
                self._last_error = ""
            try:
                if not self._serial.send_immediate("AUDIO UNMUTE"):
                    raise Esp32AudioError("could not unmute ESP32 speaker")
                time.sleep(0.03)
                if not self._serial.send_immediate("SPK BEGIN"):
                    raise Esp32AudioError("could not send SPK BEGIN")
                if not self._speaker_ready.wait(timeout_s):
                    raise Esp32AudioError("ESP32 speaker did not start")
                if self.last_error:
                    raise Esp32AudioError(self.last_error)
                self._resume_background_commands()
            except Exception:
                self._speaker_active.clear()
                self._resume_background_commands()
                raise

    def write_speaker_frame(self, pcm: bytes) -> bool:
        """Write one 20 ms signed-int16 mono frame to an open stream."""
        if not self._speaker_active.is_set():
            return False
        frame = bytes(pcm[:self.frame_bytes])
        if len(frame) < self.frame_bytes:
            frame += b"\x00" * (self.frame_bytes - len(frame))
        payload = base64.b64encode(frame).decode("ascii")
        return self._serial.send_immediate("SPK:" + payload)

    def stop_speaker_stream(self, *, abort: bool = False) -> None:
        """Close a stream opened by :meth:`start_speaker_stream`."""
        with self._mode_lock:
            if not self._speaker_active.is_set():
                return
            self._pause_background_commands()
            try:
                self._speaker_done.clear()
                self._serial.send_immediate("SPK ABORT" if abort else "SPK END")
                self._speaker_done.wait(1.5)
            finally:
                self._speaker_active.clear()
                self._resume_background_commands()

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        self._serial.send_immediate(f"AUDIO VOLUME {percent}")

    def unmute(self) -> None:
        """Explicitly restore the ES8311 speaker output."""
        self._serial.send_immediate("AUDIO UNMUTE")

    def _clear_mic_queue(self) -> None:
        with self._mic_buffer_lock:
            self._mic_pcm_buffer.clear()
        while True:
            try:
                self._mic_frames.get_nowait()
            except queue.Empty:
                return

    def _pause_background_commands(self) -> None:
        pause = getattr(self._serial, "pause_queued_writes", None)
        if callable(pause):
            pause()

    def _resume_background_commands(self) -> None:
        method = "resume_priority_commands" if self.busy else "resume_queued_writes"
        resume = getattr(self._serial, method, None)
        if callable(resume):
            resume()

    def _queue_mic_frame(self, frame: bytes) -> None:
        """Queue one normalized frame, preferring live audio if overloaded."""
        try:
            self._mic_frames.put_nowait(frame)
        except queue.Full:
            try:
                self._mic_frames.get_nowait()
            except queue.Empty:
                pass
            self._mic_frames.put_nowait(frame)
