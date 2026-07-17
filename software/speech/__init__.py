"""
speech - AURA's Speech Manager (the expression layer).

It EXPRESSES BrainManager responses as expressive, spoken output: choose a voice
profile + face emotion, hold a stable expression, animate the mouth, synthesize
via a pluggable TTS engine, and play - all on a background worker. It never
generates answers, calls an LLM, does speech recognition, changes modes, or makes
decisions.

Usage::

    from speech import SpeechManager, SpeechConfig
    from speech.tts_manager import TTSManager, Pyttsx3Engine
    from speech.audio_player import AudioPlayer, RealAudioSink
    tts = TTSManager([Pyttsx3Engine()])
    speech = SpeechManager(bus, SpeechConfig(), tts, AudioPlayer(RealAudioSink()))
    lifecycle.register(speech)           # it is a core Module
    speech.say("Hello!", mode="NORMAL")  # or it speaks ANSWER_READY automatically
"""
from .audio_player import AudioPlayer, FakeAudioSink, RealAudioSink
from .emotion_mapper import EmotionMapper, SpeakingStyle
from .speech_config import SpeechConfig
from .speech_context import SpeechContext, SpeechSnapshot, SpeechState
from .speech_manager import SpeechManager
from .speech_result import SpeechResult
from .tts_manager import FakeTTS, TTSManager, TTSEngine
from .voice_profiles import VoiceProfile, VoiceProfileRegistry

__all__ = [
    "SpeechManager", "SpeechConfig", "SpeechResult",
    "SpeechContext", "SpeechSnapshot", "SpeechState",
    "TTSManager", "TTSEngine", "FakeTTS",
    "AudioPlayer", "FakeAudioSink", "RealAudioSink",
    "EmotionMapper", "SpeakingStyle",
    "VoiceProfile", "VoiceProfileRegistry",
]
