"""
speech/tts_manager.py
=====================
Text-to-speech behind a provider abstraction. The Speech Manager depends on the
TTSEngine INTERFACE, never a concrete engine, so pyttsx3/Edge/Piper are
interchangeable and testable.

Engines:
    * FakeTTS   - deterministic, offline; returns synthetic audio + a duration
                  estimate. For tests and dry runs.
    * Pyttsx3Engine / EdgeTTSEngine / PiperEngine - real; each lazily imports its
      library so importing this module never requires any TTS package, and a
      missing engine reports unavailable instead of crashing.

An "audio clip" is an opaque object (bytes/path on the real system); this module
never plays it - the AudioPlayer does.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.logger import get_logger

from .speech_exceptions import TTSError, TTSUnavailable
from .voice_profiles import VoiceProfile

log = get_logger("speech.tts")


@dataclass(frozen=True)
class SynthesisResult:
    """Output of synthesizing one utterance."""
    audio: object                 # opaque clip (bytes / file path)
    duration_s: float
    engine: str
    sample_rate: int = 22050


@runtime_checkable
class TTSEngine(Protocol):
    """Common interface every TTS engine implements."""
    name: str
    def is_available(self) -> bool: ...
    def synthesize(self, text: str, profile: VoiceProfile) -> SynthesisResult: ...


class FakeTTS:
    """Deterministic offline engine. Estimates duration from text length so
    timing/mouth logic can be tested without audio hardware."""

    def __init__(self, name: str = "fake", *, available: bool = True,
                 fail: bool = False, chars_per_second: float = 14.0) -> None:
        self.name = name
        self._available = available
        self._fail = fail
        self._cps = chars_per_second
        self.calls = 0

    def set_available(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def synthesize(self, text: str, profile: VoiceProfile) -> SynthesisResult:
        self.calls += 1
        if not self._available:
            raise TTSUnavailable(f"engine '{self.name}' unavailable")
        if self._fail:
            raise TTSError(f"engine '{self.name}' failed")
        speed = max(0.1, profile.speed)
        duration = max(0.2, len(text) / (self._cps * speed))
        return SynthesisResult(audio=f"<audio:{self.name}:{text[:16]}>",
                               duration_s=duration, engine=self.name)


class Pyttsx3Engine:
    """Real offline engine via pyttsx3. Lazily imported."""
    name = "pyttsx3"

    def __init__(self) -> None:
        self._engine = None

    def is_available(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
            return True
        except Exception:                               # noqa: BLE001
            return False

    def synthesize(self, text: str, profile: VoiceProfile) -> SynthesisResult:
        try:
            import pyttsx3
            import tempfile
            eng = pyttsx3.init()
            eng.setProperty("rate", int(180 * profile.speed))
            eng.setProperty("volume", profile.volume)
            path = tempfile.mktemp(suffix=".wav")
            eng.save_to_file(text, path)
            eng.runAndWait()
            return SynthesisResult(audio=path, duration_s=_estimate(text, profile),
                                   engine=self.name)
        except Exception as exc:                        # noqa: BLE001
            raise TTSError(f"pyttsx3 failed: {exc}") from exc


class EdgeTTSEngine:
    """Real online engine via edge-tts. Lazily imported."""
    name = "edge"

    def __init__(self, voice: str = "en-US-AriaNeural") -> None:
        self._voice = voice

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:                               # noqa: BLE001
            return False

    def synthesize(self, text: str, profile: VoiceProfile) -> SynthesisResult:
        try:
            import asyncio, edge_tts, tempfile
            voice = profile.voice if profile.voice != "default" else self._voice
            rate = f"{int((profile.speed - 1) * 100):+d}%"
            path = tempfile.mktemp(suffix=".mp3")
            async def _run():
                comm = edge_tts.Communicate(text, voice, rate=rate)
                await comm.save(path)
            asyncio.run(_run())
            return SynthesisResult(audio=path, duration_s=_estimate(text, profile),
                                   engine=self.name)
        except Exception as exc:                        # noqa: BLE001
            raise TTSError(f"edge-tts failed: {exc}") from exc


class PiperEngine:
    """Real local neural engine via piper. Lazily imported."""
    name = "piper"

    def __init__(self, model_path: str = "") -> None:
        self._model_path = model_path

    def is_available(self) -> bool:
        try:
            import piper  # noqa: F401
            return bool(self._model_path)
        except Exception:                               # noqa: BLE001
            return False

    def synthesize(self, text: str, profile: VoiceProfile) -> SynthesisResult:
        try:
            from piper.voice import PiperVoice
            import tempfile, wave
            voice = PiperVoice.load(self._model_path)
            path = tempfile.mktemp(suffix=".wav")
            with wave.open(path, "wb") as wav:
                voice.synthesize(text, wav)
            return SynthesisResult(audio=path, duration_s=_estimate(text, profile),
                                   engine=self.name)
        except Exception as exc:                        # noqa: BLE001
            raise TTSError(f"piper failed: {exc}") from exc


def _estimate(text: str, profile: VoiceProfile) -> float:
    return max(0.2, len(text) / (14.0 * max(0.1, profile.speed)))


class TTSManager:
    """Selects an available engine (preference order) and synthesizes. Thread-safe."""

    def __init__(self, engines: list[TTSEngine], preferred: str | None = None) -> None:
        self._lock = threading.RLock()
        self._engines = {e.name: e for e in engines}
        self._preferred = preferred

    def register(self, engine: TTSEngine) -> None:
        with self._lock:
            self._engines[engine.name] = engine

    def available_engine(self) -> TTSEngine | None:
        with self._lock:
            order = ([self._preferred] if self._preferred else []) + list(self._engines)
            seen = set()
            for name in order:
                if name in seen or name not in self._engines:
                    continue
                seen.add(name)
                eng = self._engines[name]
                if _safe_available(eng):
                    return eng
        return None

    def synthesize(self, text: str, profile: VoiceProfile) -> SynthesisResult:
        engine = self.available_engine()
        if engine is None:
            raise TTSUnavailable("no TTS engine available")
        return engine.synthesize(text, profile)

    def engine_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._engines)


def _safe_available(engine: TTSEngine) -> bool:
    try:
        return engine.is_available()
    except Exception:                                   # noqa: BLE001
        return False
