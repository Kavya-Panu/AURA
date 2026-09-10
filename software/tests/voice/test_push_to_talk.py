from __future__ import annotations

from voice.backends import FakeMicrophone
from voice.push_to_talk import ListenResult, PushToTalkListener
from voice.speech_recognizer import RecognitionResult
from voice.tests._audio import silence_frame, tone_frame
from voice.voice_config import AudioConfig, STTConfig, VADConfig, VoiceConfig


def test_to_result_success():
    result = PushToTalkListener._to_result(
        RecognitionResult(
            text="What is Ohm's law?",
            language="en",
            confidence=0.95,
            duration_s=2.1,
            is_empty=False,
        ),
        0.42,
    )
    assert result.success is True
    assert result.text == "What is Ohm's law?"
    assert result.transcription_time_s == 0.42


def test_to_result_empty():
    result = PushToTalkListener._to_result(
        RecognitionResult(
            text="",
            language="en",
            confidence=0.0,
            duration_s=1.0,
            is_empty=True,
        ),
        0.1,
    )
    assert result.success is False
    assert "did not detect" in result.error


def test_to_result_rejects_uncertain_transcript():
    result = PushToTalkListener._to_result(
        RecognitionResult(
            text="possibly misunderstood words",
            language="en",
            confidence=0.18,
            duration_s=2.0,
            is_empty=False,
        ),
        0.3,
        min_confidence=0.30,
    )
    assert result.success is False
    assert result.text == "possibly misunderstood words"
    assert "repeat" in result.error.lower()


def test_buffered_wake_audio_is_transcribed_without_repeating_question():
    audio = AudioConfig(sample_rate=16_000, frame_ms=20)
    config = VoiceConfig(
        audio=audio,
        vad=VADConfig(
            start_frames=2,
            silence_timeout_s=0.10,
            short_silence_timeout_s=0.10,
            long_silence_timeout_s=0.10,
            pre_roll_ms=40,
            min_speech_s=0.05,
        ),
        stt=STTConfig(min_confidence=0.20),
    )
    listener = PushToTalkListener(
        config,
        microphone=FakeMicrophone(),
        play_cue=False,
    )

    class Recognizer:
        @staticmethod
        def recognize(_pcm):
            return RecognitionResult(
                text="Hey AURA, start focus mode",
                language="en",
                confidence=0.95,
                duration_s=0.5,
                is_empty=False,
            )

    listener._recognizer = Recognizer()
    listener._loaded = True
    listener._calibrated = True
    initial_audio = b"".join(
        [tone_frame(audio.frame_samples)] * 12
        + [silence_frame(audio.frame_samples)] * 8
    )

    result = listener.listen(initial_audio=initial_audio)

    assert result.success
    assert result.text == "Hey AURA, start focus mode"
