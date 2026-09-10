"""Wake phrase and spoken cue cannot become the question."""
import ast
from pathlib import Path
import pytest
from voice.wake_handoff import acknowledge_wake


def test_acknowledgement_finishes_before_fresh_capture():
    events = []
    class Mic:
        def close(self):
            events.append("close")
    def speak(text):
        events.extend([text, "playback_finished"])
    acknowledge_wake(Mic(), speak, sleep=lambda seconds: events.append(seconds))
    events.append("question_capture")
    assert events == ["close", "Hmm?", "playback_finished", "close", .2,
                      "question_capture"]


def test_failed_cue_still_closes_old_audio():
    closed = []
    class Mic:
        def close(self):
            closed.append(True)
    def fail(text):
        raise RuntimeError("speaker unavailable")
    with pytest.raises(RuntimeError):
        acknowledge_wake(Mic(), fail, sleep=lambda seconds: None)
    assert len(closed) == 2


def test_live_wake_loop_does_not_replay_activation_audio():
    source = Path(__file__).resolve().parents[2] / "run_aura_brain.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    loop = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "hands_free_loop")
    assert not any(isinstance(node, ast.Attribute) and node.attr == "buffered_audio"
                   for node in ast.walk(loop))
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "play_wake_acknowledgement"
               for node in ast.walk(loop))
