"""Local visual question answering for AURA's shared camera."""
from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger("vision.object_vision")


@dataclass(frozen=True)
class ObjectObservation:
    label: str
    confidence: float
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class VisualAnswer:
    text: str
    observations: tuple[ObjectObservation, ...] = ()
    success: bool = True
    error: str = ""


class _MediaPipeDetector:
    """EfficientDet-Lite2 adapter returning AURA observations."""

    def __init__(self, model_path: Path, score_threshold: float) -> None:
        import mediapipe as mp

        self._mp = mp
        options = mp.tasks.vision.ObjectDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            max_results=10,
            score_threshold=score_threshold,
        )
        self._detector = mp.tasks.vision.ObjectDetector.create_from_options(options)

    def detect(self, frame) -> list[ObjectObservation]:
        import cv2

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._detector.detect(image)
        observations: list[ObjectObservation] = []
        for detection in result.detections:
            if not detection.categories:
                continue
            category = detection.categories[0]
            label = (category.category_name or category.display_name or "object").strip()
            box = detection.bounding_box
            observations.append(
                ObjectObservation(
                    label.casefold(),
                    float(category.score or 0.0),
                    (int(box.origin_x), int(box.origin_y), int(box.width), int(box.height)),
                )
            )
        observations.sort(key=lambda item: item.confidence, reverse=True)
        return observations

    def close(self) -> None:
        self._detector.close()


class ObjectVisionService:
    """Answers camera questions with the local MediaPipe object detector."""

    _VISUAL_QUESTION = re.compile(
        r"\b(?:what\s+(?:can|do)\s+you\s+see|what\s+am\s+i\s+holding|"
        r"what\s+is\s+(?:this|that)(?:\s+in\s+my\s+hand)?|"
        r"what(?:\s+is|'s)\s+in\s+my\s+hand|"
        r"what\s+(?:have|do)\s+i\s+(?:have|got)\s+in\s+my\s+hand|"
        r"describe\s+(?:this|that|what\s+you\s+see)|"
        r"look\s+at\s+(?:this|that)|can\s+you\s+see\s+(?:this|that|me)|"
        r"identify\s+(?:this|that|the\s+object)|"
        r"what\s+(?:electronic\s+)?(?:object|thing|device|tool)\s+is\s+this)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        models_dir: str | Path,
        *,
        confidence_threshold: float = 0.25,
        detector_factory: Callable[[], object] | None = None,
    ) -> None:
        self._models_dir = Path(models_dir)
        self._confidence = max(0.1, min(0.95, float(confidence_threshold)))
        self._detector_factory = detector_factory
        self._detector = None
        self._lock = threading.RLock()
        self._error = ""

    @classmethod
    def handles(cls, question: str) -> bool:
        return bool(cls._VISUAL_QUESTION.search(" ".join(question.split())))

    @property
    def ready(self) -> bool:
        return self._ensure_detector()

    @property
    def error(self) -> str:
        return self._error

    def describe(self, question: str, frame) -> VisualAnswer:
        if frame is None:
            return VisualAnswer(
                "I cannot get a camera image right now.",
                success=False,
                error="camera frame unavailable",
            )

        return self._fallback_answer(question, self.detect(frame))

    def detect(self, frame) -> list[ObjectObservation]:
        if not self._ensure_detector():
            return []
        try:
            with self._lock:
                observations = self._detector.detect(frame)
            return list(observations or [])[:10]
        except Exception as exc:  # noqa: BLE001
            self._error = f"MediaPipe detection failed: {exc}"
            log.warning("%s", self._error)
            return []

    def focus_frame(
        self,
        question: str,
        frame,
    ) -> tuple[object, tuple[ObjectObservation, ...], str]:
        """Crop to a likely held object before an online image search.

        Web matching against the whole camera view tends to identify the
        user's hand, clothes, or room.  The local detector is fast and gives
        us a useful bounding box without uploading another image.  If it
        cannot find a sensible target, the original frame is returned.
        """
        if frame is None:
            return frame, (), ""
        observations = self.detect(frame)
        normalized = question.casefold()
        wants_object = bool(
            re.search(
                r"\b(?:this|that|object|item|holding|hold|in\s+my\s+hand)\b",
                normalized,
            )
        )
        if not wants_object or not observations:
            return frame, tuple(observations), ""

        height, width = frame.shape[:2]
        ignored = {
            "arm", "finger", "hand", "human", "person", "skin", "thumb",
            "wrist",
        }
        candidates: list[tuple[float, ObjectObservation]] = []
        for item in observations:
            if item.label.casefold() in ignored:
                continue
            x, y, box_w, box_h = item.box
            if box_w < 12 or box_h < 12:
                continue
            area_ratio = (box_w * box_h) / max(1.0, float(width * height))
            center_x = x + box_w / 2.0
            center_y = y + box_h / 2.0
            distance = (
                abs(center_x - width / 2.0) / max(1.0, width / 2.0)
                + abs(center_y - height / 2.0) / max(1.0, height / 2.0)
            ) / 2.0
            score = item.confidence + min(0.35, area_ratio) + 0.18 * (1.0 - distance)
            candidates.append((score, item))

        if not candidates:
            return frame, tuple(observations), ""
        _score, target = max(candidates, key=lambda value: value[0])
        x, y, box_w, box_h = target.box
        padding = round(max(box_w, box_h) * 0.28)
        left = max(0, x - padding)
        top = max(0, y - padding)
        right = min(width, x + box_w + padding)
        bottom = min(height, y + box_h + padding)
        if right - left < 32 or bottom - top < 32:
            return frame, tuple(observations), ""
        # Avoid an unnecessary crop when the detection already covers nearly
        # the entire image.
        crop_ratio = ((right - left) * (bottom - top)) / max(1.0, width * height)
        if crop_ratio > 0.88:
            return frame, tuple(observations), target.label
        return frame[top:bottom, left:right].copy(), tuple(observations), target.label

    def close(self) -> None:
        with self._lock:
            method = getattr(self._detector, "close", None)
            if method:
                method()
            self._detector = None

    def _ensure_detector(self) -> bool:
        with self._lock:
            if self._detector is not None:
                return True
            try:
                if self._detector_factory is not None:
                    self._detector = self._detector_factory()
                else:
                    model = self._models_dir / "efficientdet_lite2.tflite"
                    if not model.is_file():
                        raise RuntimeError(f"missing model file: {model.name}")
                    self._detector = _MediaPipeDetector(model, self._confidence)
                log.info("MediaPipe object detector ready")
                return True
            except Exception as exc:  # noqa: BLE001
                self._error = f"MediaPipe detector unavailable: {exc}"
                log.warning("%s", self._error)
                return False

    def _fallback_answer(
        self,
        question: str,
        observations: list[ObjectObservation],
    ) -> VisualAnswer:
        if not observations:
            return VisualAnswer(
                "I can see the camera image, but I cannot identify the object clearly.",
                (),
                False,
                self._error,
            )
        normalized = question.casefold()
        non_people = [item for item in observations if item.label != "person"]
        if "holding" in normalized or "in my hand" in normalized:
            if non_people:
                text = f"I can see {self._article(non_people[0].label)} near your hand."
            else:
                text = "I can see you, but I cannot identify what you are holding."
        elif re.search(r"\bwhat\s+is\s+(?:this|that)\b", normalized):
            target = non_people[0] if non_people else observations[0]
            text = f"That looks like {self._article(target.label)}."
        else:
            text = "I can see " + self._summarise(observations) + "."
        return VisualAnswer(text, tuple(observations), True, self._error)

    @classmethod
    def _summarise(cls, observations: list[ObjectObservation]) -> str:
        counts = Counter(item.label for item in observations)
        ordered_labels = list(dict.fromkeys(item.label for item in observations))
        parts: list[str] = []
        for label in ordered_labels[:4]:
            count = counts[label]
            parts.append(
                cls._article(label)
                if count == 1
                else f"{cls._number(count)} {cls._plural(label)}"
            )
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return parts[0] + " and " + parts[1]
        return ", ".join(parts[:-1]) + ", and " + parts[-1]

    @staticmethod
    def _article(label: str) -> str:
        article = "an" if label[:1].casefold() in "aeiou" else "a"
        return f"{article} {label}"

    @staticmethod
    def _plural(label: str) -> str:
        if label.endswith("s"):
            return label
        if label.endswith(("ch", "sh", "x")):
            return label + "es"
        return label + "s"

    @staticmethod
    def _number(count: int) -> str:
        words = {2: "two", 3: "three", 4: "four", 5: "five"}
        return words.get(count, str(count))
