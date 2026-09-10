from __future__ import annotations

from voice.listening_modes import is_stop_phrase, strip_wake_phrase
from voice.tests._audio import silence_frame, tone_frame
from voice.vad import Endpointer
from voice.voice_config import AudioConfig, VADConfig


def test_short_phrase_waits_through_a_one_second_pause():
    audio = AudioConfig(frame_ms=20)
    cfg = VADConfig(
        start_frames=2, silence_timeout_s=0.6,
        short_silence_timeout_s=1.4, long_silence_timeout_s=1.0,
        short_utterance_s=1.5, min_speech_s=0.0,
    )
    endpointer = Endpointer(audio, cfg)
    speech = tone_frame(audio.frame_samples)
    silence = silence_frame(audio.frame_samples)

    for frame in [speech] * 10 + [silence] * 50:
        assert endpointer.process(frame) is None
    assert endpointer.in_speech is True

    completed = None
    for frame in [silence] * 25:
        completed = endpointer.process(frame)
        if completed is not None:
            break
    assert completed is not None


def test_calibration_raises_threshold_above_room_noise():
    audio = AudioConfig(frame_ms=20)
    endpointer = Endpointer(audio, VADConfig())
    room_noise = tone_frame(audio.frame_samples, amplitude=500)
    endpointer.calibrate([room_noise] * 40)
    assert endpointer.noise_floor > 0.0
    assert endpointer.speech_threshold > endpointer.noise_floor


def test_wake_phrase_extraction_and_stop_phrase():
    assert strip_wake_phrase("Hey AURA, explain Ohm's law") == "explain Ohm's law"
    assert strip_wake_phrase("Someone else is speaking") is None
    assert is_stop_phrase("AURA stop") is True
    assert is_stop_phrase("AURA shut up!") is True
    assert is_stop_phrase("AURA keep quiet.") is True
    assert is_stop_phrase("please stop") is False
    assert is_stop_phrase("stop") is False
