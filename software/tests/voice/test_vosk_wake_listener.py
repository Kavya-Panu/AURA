from voice.backends import FakeMicrophone
from voice.voice_config import AudioConfig
from voice.vosk_wake_listener import VoskWakeWordListener


def test_accepts_expected_pronunciation_variants():
    for phrase in (
        "hey aura",
        "Hey Ora",
        "hey or a",
        "hi aura",
        "Hi Ora",
        "okay aura",
        "ok aura",
    ):
        assert VoskWakeWordListener._contains_wake_phrase(phrase)


def test_rejects_ordinary_speech_and_name_without_trigger():
    for phrase in (
        "please explain Ohm's law",
        "aura",
        "the orange robot",
        "hey Arduino",
    ):
        assert not VoskWakeWordListener._contains_wake_phrase(phrase)


def test_extracts_partial_and_final_results():
    assert VoskWakeWordListener._extract_text(
        '{"partial": "hey ora"}', False
    ) == "hey ora"
    assert VoskWakeWordListener._extract_text(
        '{"text": "hey aura"}', True
    ) == "hey aura"
    assert VoskWakeWordListener._extract_text("not-json", False) == ""


def test_stop_grammar_requires_an_aura_addressed_command():
    for phrase in (
        "aura stop",
        "AURA shut up",
        "aura keep quiet",
        "ora stop",
    ):
        assert VoskWakeWordListener._contains_stop_phrase(phrase)

    for phrase in ("stop", "please stop", "keep quiet", "aura"):
        assert not VoskWakeWordListener._contains_stop_phrase(phrase)


def test_wake_detection_hands_consumed_audio_to_question_listener(tmp_path):
    audio = AudioConfig(sample_rate=16_000, frame_ms=20)
    frame = b"\x01\x00" * audio.frame_samples
    microphone = FakeMicrophone([frame] * 12)

    class PartialWakeRecognizer:
        def __init__(self, *_args):
            pass

        def SetWords(self, _enabled):
            pass

        def AcceptWaveform(self, _frame):
            return False

        def PartialResult(self):
            return '{"partial": "hey ora"}'

    listener = VoskWakeWordListener(audio, microphone, tmp_path)
    listener._loaded = True
    listener._model = object()
    listener._recognizer_type = PartialWakeRecognizer

    result = listener.wait(timeout_s=1.0)

    assert result.detected
    assert result.buffered_audio == frame * 2
    # The stream intentionally remains open for a gapless Whisper handoff.
    assert microphone.is_open()
    microphone.close()
