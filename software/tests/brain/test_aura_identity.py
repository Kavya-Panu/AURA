from brain.aura_identity import (
    AURA_SYSTEM_OVERVIEW,
    is_aura_identity_question,
)


def test_identity_questions_are_detected():
    assert is_aura_identity_question("What are you?")
    assert is_aura_identity_question("Hey AURA, what can you do?")
    assert is_aura_identity_question("Explain your system and program")
    assert is_aura_identity_question("How does AURA work?")


def test_normal_questions_are_not_identity_questions():
    assert not is_aura_identity_question("What is Ohm's law?")
    assert not is_aura_identity_question("Explain an embedded system")


def test_overview_describes_real_stack():
    for fact in ("Hey AURA", "emotions", "follow your face", "focus mode"):
        assert fact in AURA_SYSTEM_OVERVIEW


def test_overview_avoids_deep_technical_details():
    for detail in ("ESP32-S3", "ILI9341", "Whisper", "Qwen3", "OpenCV"):
        assert detail not in AURA_SYSTEM_OVERVIEW
