from __future__ import annotations

import numpy as np

from vision.object_vision import ObjectObservation, ObjectVisionService


class _Detector:
    def detect(self, frame):
        assert frame.shape == (80, 120, 3)
        return [
            ObjectObservation("person", 0.96, (10, 10, 60, 60)),
            ObjectObservation("bottle", 0.88, (70, 15, 25, 45)),
            ObjectObservation("bottle", 0.70, (2, 2, 12, 20)),
        ]

def _service() -> ObjectVisionService:
    return ObjectVisionService(
        ".",
        detector_factory=_Detector,
    )


def test_visual_intent_is_specific() -> None:
    assert ObjectVisionService.handles("Hey AURA, what can you see?")
    assert ObjectVisionService.handles("What am I holding?")
    assert ObjectVisionService.handles("What is this in my hand?")
    assert ObjectVisionService.handles("AURA, what is in my hand?")
    assert ObjectVisionService.handles("What's in my hand?")
    assert ObjectVisionService.handles("What have I got in my hand?")
    assert ObjectVisionService.handles("Look at this")
    assert not ObjectVisionService.handles("Can you see why my code failed?")


def test_describes_detected_objects_concisely() -> None:
    answer = _service().describe(
        "What can you see?",
        np.zeros((80, 120, 3), dtype=np.uint8),
    )
    assert answer.success
    assert answer.text == "I can see a person and two bottles."
    assert len(answer.observations) == 3


def test_holding_question_prefers_non_person_object() -> None:
    answer = _service().describe(
        "What is this in my hand?",
        np.zeros((80, 120, 3), dtype=np.uint8),
    )
    assert answer.text == "I can see a bottle near your hand."


def test_holding_question_crops_to_non_person_object() -> None:
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    focused, observations, label = _service().focus_frame(
        "What is in my hand?",
        frame,
    )

    assert label == "bottle"
    assert len(observations) == 3
    assert focused.shape[0] < frame.shape[0]
    assert focused.shape[1] < frame.shape[1]


def test_missing_camera_frame_has_clear_answer() -> None:
    answer = _service().describe("What can you see?", None)
    assert not answer.success
    assert "camera image" in answer.text
