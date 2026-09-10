"""Free-tier Spotify Desktop control with an ESP32 speaker/visualizer relay.

Spotify itself remains the player.  AURA uses Windows media-session controls
for play/pause/skip and WASAPI loopback only as a real-time output route to the
robot's ES8311 speaker.  Audio is never saved.
"""
from __future__ import annotations

import asyncio
import base64
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.logger import get_logger
from hardware import CommandPriority, HardwareManager

log = get_logger("aura.music")


@dataclass(frozen=True)
class TrackInfo:
    title: str = "Spotify"
    artist: str = ""
    playing: bool = False


class WindowsSpotify:
    """Small Windows GSMTC/keyboard adapter for the Spotify desktop app."""

    def __init__(self) -> None:
        self._spotify_exe = Path.home() / "AppData/Roaming/Spotify/Spotify.exe"

    async def _session(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )

        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        for session in manager.get_sessions():
            if "spotify" in session.source_app_user_model_id.lower():
                return session
        return None

    async def _snapshot_async(self) -> TrackInfo:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus,
        )

        session = await self._session()
        if session is None:
            return TrackInfo()
        props = await session.try_get_media_properties_async()
        status = session.get_playback_info().playback_status
        return TrackInfo(
            title=str(props.title or "Spotify"),
            artist=str(props.artist or ""),
            playing=(
                status
                == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
            ),
        )

    def snapshot(self) -> TrackInfo:
        try:
            return asyncio.run(self._snapshot_async())
        except Exception as exc:  # noqa: BLE001
            log.debug("Spotify metadata unavailable: %s", exc)
            return TrackInfo()

    async def _control_async(self, action: str) -> bool:
        session = await self._session()
        if session is None:
            return False
        method = {
            "play": session.try_play_async,
            "pause": session.try_pause_async,
            "next": session.try_skip_next_async,
            "previous": session.try_skip_previous_async,
        }[action]
        return bool(await method())

    def control(self, action: str) -> bool:
        try:
            return asyncio.run(self._control_async(action))
        except Exception as exc:  # noqa: BLE001
            log.warning("Spotify %s failed: %s", action, exc)
            return False

    def ensure_open(self) -> bool:
        if not self._spotify_exe.exists():
            return False
        try:
            subprocess.Popen(
                [str(self._spotify_exe)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False

    def search_and_play(self, query: str) -> bool:
        """Use Spotify's documented keyboard search on the desktop app.

        Spotify Free does not expose remote playback through its public API.
        This deliberately controls the user's installed app instead.
        """
        query = " ".join(query.split()).strip()
        if not query or not self.ensure_open():
            return False
        try:
            from pywinauto import Desktop, mouse
            from pywinauto.keyboard import send_keys

            deadline = time.monotonic() + 8.0
            window = None
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(title_re=".*Spotify.*")
                if windows:
                    window = windows[0]
                    break
                time.sleep(0.25)
            if window is None:
                return False

            window.restore()
            window.set_focus()
            # Ctrl+L is Spotify's official Windows shortcut for Search.  The
            # first Tab chooses the leading suggestion, and Enter activates it.
            send_keys("^l")
            time.sleep(0.20)
            send_keys("^a")
            send_keys(query, with_spaces=True)
            time.sleep(1.0)
            # Enter submits the exact query. Spotify Free's Chromium UI does
            # not expose the result buttons through Windows UI Automation, so
            # activate the stable Top Result play button by window-relative
            # position after the result page has settled.
            send_keys("{ENTER}")
            time.sleep(1.8)
            bounds = window.rectangle()
            mouse.click(coords=(
                bounds.left + int(bounds.width() * 0.69),
                bounds.top + int(bounds.height() * 0.20),
            ))
            time.sleep(1.0)
            return self.snapshot().playing
        except Exception as exc:  # noqa: BLE001
            log.warning("Spotify search automation failed: %s", exc)
            return False


class MusicController:
    """Own Spotify commands, live audio routing, and the ESP32 music screen."""

    name = "music"

    _PLAY_RE = re.compile(
        r"^(?:please\s+)?(?:play|put on|listen to)\s+(.+?)"
        r"(?:\s+on spotify)?[.!?]*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        hardware: HardwareManager,
        *,
        enabled: bool = True,
        capture_device: str = "",
    ) -> None:
        self._hardware = hardware
        self._enabled = bool(enabled)
        self._capture_device = str(capture_device).strip()
        self._spotify = WindowsSpotify()
        self._running = threading.Event()
        self._active = threading.Event()
        self._relay_stop = threading.Event()
        self._relay_thread: threading.Thread | None = None
        self._metadata_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_track = TrackInfo()
        self._paused_for_aura = False

    def initialize(self) -> None:
        pass

    def start(self) -> None:
        if not self._enabled or self._running.is_set():
            return
        self._running.set()
        self._metadata_thread = threading.Thread(
            target=self._metadata_loop,
            name="spotify-metadata",
            daemon=True,
        )
        self._metadata_thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._active.clear()
        self._stop_relay()
        if self._metadata_thread is not None:
            self._metadata_thread.join(timeout=2.0)
            self._metadata_thread = None
        try:
            self._hardware.send_face_command("MUSIC STOP")
        except Exception:  # noqa: BLE001
            pass

    close = stop

    def health_check(self) -> bool:
        return self._enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active(self) -> bool:
        return self._active.is_set()

    def handles(self, text: str) -> bool:
        cleaned = self._clean(text)
        if self._PLAY_RE.match(cleaned):
            return True
        return cleaned in {
            "play music", "pause", "pause music", "pause the music",
            "resume", "resume music", "continue music", "continue the music",
            "next", "next song", "next track",
            "previous", "previous song", "previous track",
            "stop music", "stop the music", "turn off music",
            "what song is playing", "what is playing", "music status",
        }

    def handle(self, text: str, speak: Callable[[str], None]) -> bool:
        if not self._enabled:
            speak("Music mode is disabled.")
            return True
        command = self._clean(text)

        # ``play music`` means resume/start the current Spotify session.  It
        # also matches the general "play <query>" pattern, so handle this exact
        # control command first instead of searching Spotify for a track named
        # simply "music".
        if command == "play music":
            self._spotify.control("play")
            self._activate()
            return True

        match = self._PLAY_RE.match(command)
        if match:
            query = match.group(1).strip()
            speak(f"Playing {query}.")
            if not self._spotify.search_and_play(query):
                speak("I could not control Spotify. Please open Spotify and try again.")
                return True
            self._activate()
            return True
        if command in {"pause", "pause music", "pause the music"}:
            self._spotify.control("pause")
            self._stop_relay()
            self._send("MUSIC PAUSE 1")
            return True
        if command in {"resume", "resume music", "continue music", "continue the music"}:
            self._spotify.control("play")
            self._activate()
            return True
        if command in {"next", "next song", "next track"}:
            self._spotify.control("next")
            self._activate()
            return True
        if command in {"previous", "previous song", "previous track"}:
            self._spotify.control("previous")
            self._activate()
            return True
        if command in {"stop music", "stop the music", "turn off music"}:
            self._spotify.control("pause")
            self._active.clear()
            self._stop_relay()
            self._send("MUSIC STOP")
            return True
        if command in {"what song is playing", "what is playing", "music status"}:
            info = self._spotify.snapshot()
            if info.title and info.title != "Spotify":
                speak(f"{info.title} by {info.artist}." if info.artist else info.title)
            else:
                speak("Spotify is not playing a song.")
            return True
        return False

    def status_text(self) -> str:
        info = self._spotify.snapshot()
        state = "playing" if info.playing else "paused"
        device = self._capture_device or "Windows default output"
        return f"{state}: {info.title} - {info.artist}; capture: {device}"

    def interrupt_for_assistant(self) -> bool:
        """Pause an active track so wake/listen/TTS can own the speaker."""
        if not self._active.is_set():
            return False
        info = self._spotify.snapshot()
        self._paused_for_aura = bool(info.playing)
        if self._paused_for_aura:
            self._spotify.control("pause")
        self._stop_relay()
        self._send("MUSIC HIDE")
        return self._paused_for_aura

    def resume_after_assistant(self) -> None:
        if not self._active.is_set():
            self._paused_for_aura = False
            return
        if self._paused_for_aura:
            self._spotify.control("play")
        self._paused_for_aura = False
        self._send("MUSIC SHOW")
        self._send("MUSIC PAUSE 0")
        self._start_relay()

    def _activate(self) -> None:
        self._active.set()
        self._send("MUSIC START")
        self._send("MUSIC PAUSE 0")
        self._send_metadata(self._spotify.snapshot())
        self._start_relay()

    def _start_relay(self) -> None:
        with self._lock:
            if self._relay_thread is not None and self._relay_thread.is_alive():
                return
            self._relay_stop.clear()
            self._relay_thread = threading.Thread(
                target=self._relay_loop,
                name="spotify-audio-relay",
                daemon=True,
            )
            self._relay_thread.start()

    def _stop_relay(self) -> None:
        with self._lock:
            thread = self._relay_thread
            self._relay_stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.5)
        with self._lock:
            if self._relay_thread is thread:
                self._relay_thread = None

    def _relay_loop(self) -> None:
        try:
            import numpy as np
            import soundcard as sc

            speakers = sc.all_speakers()
            speaker = None
            if self._capture_device:
                needle = self._capture_device.casefold()
                speaker = next(
                    (item for item in speakers if needle in item.name.casefold()),
                    None,
                )
            speaker = speaker or sc.default_speaker()
            loopback = sc.get_microphone(speaker.id, include_loopback=True)
            source_rate = 48_000
            block_frames = 960  # 20 ms

            self._hardware.audio_link.start_speaker_stream()
            log.info("Spotify audio relay using %s", speaker.name)
            level_deadline = 0.0
            with loopback.recorder(
                samplerate=source_rate,
                channels=2,
                blocksize=block_frames,
            ) as recorder:
                while (
                    self._running.is_set()
                    and self._active.is_set()
                    and not self._relay_stop.is_set()
                ):
                    data = recorder.record(numframes=block_frames)
                    if data is None or len(data) == 0:
                        continue
                    mono = np.asarray(data, dtype=np.float32).mean(axis=1)
                    mono -= float(np.mean(mono))
                    # Exact 48k -> 16k conversion: one output sample per three.
                    mono = mono[::3][: self._hardware.audio_link.frame_samples]
                    if len(mono) < self._hardware.audio_link.frame_samples:
                        mono = np.pad(
                            mono,
                            (0, self._hardware.audio_link.frame_samples - len(mono)),
                        )
                    rms = float(np.sqrt(np.mean(np.square(mono))))
                    if rms > 1.0e-5:
                        mono *= float(np.clip(0.11 / rms, 0.65, 2.4))
                    mono = np.tanh(mono * 1.05)
                    peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
                    if peak > 0.58:
                        mono *= 0.58 / peak
                    pcm = (mono * 32767.0).astype("<i2", copy=False).tobytes()
                    if not self._hardware.audio_link.write_speaker_frame(pcm):
                        raise RuntimeError("ESP32 speaker stream disconnected")

                    now = time.monotonic()
                    if now >= level_deadline:
                        level = max(0, min(100, round(rms * 620)))
                        self._send(f"MUSIC LEVEL {level}", low_priority=True)
                        level_deadline = now + 0.10
        except Exception as exc:  # noqa: BLE001
            log.warning("Spotify audio relay stopped: %s", exc)
        finally:
            try:
                self._hardware.audio_link.stop_speaker_stream(abort=False)
            except Exception:  # noqa: BLE001
                pass

    def _metadata_loop(self) -> None:
        while self._running.is_set():
            if self._active.is_set():
                info = self._spotify.snapshot()
                if (info.title, info.artist) != (
                    self._last_track.title,
                    self._last_track.artist,
                ):
                    self._send_metadata(info)
                if not info.playing and self._relay_thread is not None:
                    self._stop_relay()
                    self._send("MUSIC PAUSE 1")
                elif info.playing and self._relay_thread is None and not self._paused_for_aura:
                    self._send("MUSIC PAUSE 0")
                    self._start_relay()
                self._last_track = info
            time.sleep(0.75)

    def _send_metadata(self, info: TrackInfo) -> None:
        title = info.title[:42]
        artist = info.artist[:34]
        payload = base64.b64encode(f"{title}\n{artist}".encode("utf-8")).decode("ascii")
        self._send("MUSIC META:" + payload)
        self._last_track = info

    def _send(self, line: str, *, low_priority: bool = False) -> None:
        try:
            self._hardware.send_face_command(
                line,
                priority=(
                    # Level frames drive the active visualizer while the
                    # speaker stream is open. Latest-only queueing prevents
                    # backlog; HIGH allows them through the audio gate.
                    CommandPriority.LOW
                    if low_priority and not line.startswith("MUSIC LEVEL ")
                    else CommandPriority.HIGH
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("music display command dropped: %s", exc)

    @staticmethod
    def _clean(text: str) -> str:
        cleaned = re.sub(
            r"^\s*(?:(?:hey|hi|okay|ok)\s+)?(?:aura|ora)\b[\s,.:;!?-]*",
            "",
            str(text),
            flags=re.IGNORECASE,
        )
        return " ".join(cleaned.casefold().split()).strip(" .!?\t\r\n")
