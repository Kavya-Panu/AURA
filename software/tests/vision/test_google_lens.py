from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from vision.google_lens import GoogleLensService


def _item(**values):
    return SimpleNamespace(**values)


def _frame():
    # Encoding fixture with visible detail, independent of the fake API labels.
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[10:30, 10:30] = 180
    return frame


class _Client:
    def __init__(self, web, error: str = "") -> None:
        self.web = web
        self.error = error
        self.calls = 0

    def web_detection(self, *, image, max_results):
        assert bytes(image).startswith(b"\xff\xd8")
        assert max_results == 10
        self.calls += 1
        return _item(
            web_detection=self.web,
            error=_item(message=self.error),
        )


class _BatchClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = 0

    def annotate_image(self, request):
        assert bytes(request["image"]).startswith(b"\xff\xd8")
        assert len(request["features"]) == 3
        self.calls += 1
        return self.response


def _service(client: _Client) -> GoogleLensService:
    return GoogleLensService(
        client_factory=lambda: client,
        image_factory=lambda **values: values["content"],
    )


def test_precise_web_entity_beats_generic_best_guess() -> None:
    web = _item(
        best_guess_labels=[_item(label="electronics")],
        web_entities=[
            _item(description="Arduino Uno Rev3", score=0.92),
            _item(description="microcontroller", score=0.60),
        ],
        pages_with_matching_images=[
            _item(
                page_title="Arduino Uno Rev3 | Arduino Documentation",
                url="https://docs.arduino.cc/hardware/uno-rev3/",
            )
        ],
    )
    result = _service(_Client(web)).identify(
        "What is this in my hand?",
        _frame(),
    )

    assert result.success
    assert "Arduino Uno Rev3" in result.text
    assert result.sources[0].url.startswith("https://")


def test_best_guess_label_generates_short_spoken_answer() -> None:
    web = _item(
        best_guess_labels=[_item(label="Raspberry Pi 4 Model B")],
        web_entities=[],
        pages_with_matching_images=[],
    )
    result = _service(_Client(web)).identify(
        "Identify this",
        _frame(),
    )

    assert result.text == "That appears to be Raspberry Pi 4 Model B."


def test_held_object_beats_hand_and_person_context() -> None:
    web = _item(
        best_guess_labels=[_item(label="hand")],
        web_entities=[
            _item(description="Plastic bottle", score=0.91),
            _item(description="Bottle", score=0.82),
            _item(description="Human hand", score=0.95),
            _item(description="Plastic", score=0.67),
        ],
        pages_with_matching_images=[],
    )
    result = _service(_Client(web)).identify(
        "AURA, what is in my hand?",
        _frame(),
    )

    assert result.success
    assert result.text == "That appears to be a plastic bottle."
    assert result.candidates[0] == "Plastic bottle"
    assert "hand" not in {item.casefold() for item in result.candidates}


def test_combined_google_features_override_unrelated_web_brand() -> None:
    web = _item(
        best_guess_labels=[_item(label="H&M")],
        web_entities=[_item(description="H&M", score=0.78)],
        pages_with_matching_images=[],
    )
    response = _item(
        web_detection=web,
        label_annotations=[_item(description="Bottle", score=0.91)],
        localized_object_annotations=[_item(name="Bottle", score=0.93)],
        error=_item(message=""),
    )
    client = _BatchClient(response)
    result = _service(client).identify(
        "What is in my hand?",
        _frame(),
    )

    assert result.success
    assert result.text == "That appears to be a bottle."
    assert client.calls == 1


def test_weak_brand_only_match_is_refused() -> None:
    web = _item(
        best_guess_labels=[_item(label="H&M")],
        web_entities=[],
        pages_with_matching_images=[],
    )
    result = _service(_Client(web)).identify(
        "What is in my hand?",
        _frame(),
    )

    assert not result.success
    assert "cannot identify" in result.text.casefold()


def test_google_error_returns_safe_local_fallback_signal() -> None:
    web = _item(
        best_guess_labels=[],
        web_entities=[],
        pages_with_matching_images=[],
    )
    result = _service(_Client(web, "quota exceeded")).identify(
        "What is this?",
        _frame(),
    )

    assert not result.success
    assert "failed" in result.text.casefold()
    assert "quota exceeded" in result.error


def test_missing_frame_never_calls_google() -> None:
    client = _Client(_item())
    result = _service(client).identify("What is this?", None)

    assert not result.success
    assert client.calls == 0


def test_flat_camera_images_are_rejected_without_upload():
    for colour in ((0, 0, 0), (255, 255, 255), (0, 0, 255)):
        client = _Client(_item())
        frame = np.full((40, 40, 3), colour, dtype=np.uint8)
        result = _service(client).identify("What is this?", frame)
        assert not result.success
        assert "detail" in result.error
        assert client.calls == 0


def test_colour_material_and_hand_only_results_do_not_identify_an_object():
    for label in ("White", "Plastic", "Human hand", "Dairy"):
        web = _item(best_guess_labels=[_item(label=label)],
                    web_entities=[_item(description=label, score=1.0)],
                    pages_with_matching_images=[])
        result = _service(_Client(web)).identify("What am I holding?", _frame())
        assert not result.success
        assert not result.text.startswith("That appears")
