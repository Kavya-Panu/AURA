"""Private, local face recognition for AURA using OpenCV SFace.

Only averaged numerical embeddings are stored. Camera frames and cropped face
images are never written to disk.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from core.logger import get_logger

log = get_logger("vision.face_recognizer")

StatusCallback = Callable[[str], None]
IdentityCallback = Callable[[str, float], None]


@dataclass(frozen=True)
class FaceRecognition:
    """Recognition result for one detected face."""

    name: str = "Unknown"
    score: float = 0.0
    known: bool = False
    enrolling: bool = False
    enrollment_progress: int = 0
    enrollment_total: int = 0


class SFaceRecognizer:
    """Enroll and recognise faces using OpenCV's SFace embedding model."""

    def __init__(
        self,
        model_path: Path,
        database_path: Path,
        *,
        threshold: float = 0.40,
        enrollment_samples: int = 12,
        stable_frames: int = 3,
        greeting_cooldown_s: float = 300.0,
        status: StatusCallback | None = None,
        on_recognized: IdentityCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model_path = Path(model_path)
        self._database_path = Path(database_path)
        self._threshold = max(0.25, min(0.90, float(threshold)))
        self._sample_target = max(5, min(30, int(enrollment_samples)))
        self._stable_frames = max(2, int(stable_frames))
        self._greeting_cooldown = max(10.0, float(greeting_cooldown_s))
        self._status = status or (lambda _message: None)
        self._on_recognized = on_recognized or (lambda _name, _score: None)
        self._clock = clock
        self._lock = threading.RLock()

        self._cv2 = None
        self._engine = None
        self._templates: dict[str, np.ndarray] = {}
        self._enrollment_name: str | None = None
        self._enrollment_features: list[np.ndarray] = []
        self._candidate = ""
        self._candidate_frames = 0
        self._last_announced: dict[str, float] = {}

    def initialize(self, cv2_module) -> None:
        """Load the SFace model and locally stored templates."""
        if not self._model_path.is_file():
            raise RuntimeError(f"SFace model is missing: {self._model_path}")
        if not hasattr(cv2_module, "FaceRecognizerSF_create"):
            raise RuntimeError("This OpenCV build does not include FaceRecognizerSF")
        self._cv2 = cv2_module
        self._engine = cv2_module.FaceRecognizerSF_create(
            str(self._model_path), ""
        )
        self._load_database()
        self._status(
            f"Face recognition ready; {len(self._templates)} person(s) enrolled."
        )

    @property
    def ready(self) -> bool:
        return self._engine is not None

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._templates, key=str.casefold))

    def begin_enrollment(self, name: str) -> bool:
        """Begin collecting several embeddings for one named person."""
        clean = " ".join(name.strip().split())
        if not re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,39}", clean):
            self._status("Use a name containing letters, spaces, apostrophes or hyphens.")
            return False
        if not self.ready:
            self._status("Face recognition is not ready.")
            return False
        with self._lock:
            self._enrollment_name = clean
            self._enrollment_features.clear()
        self._status(
            f"Enrolling {clean}: look at the camera and slowly turn your head a little."
        )
        return True

    def cancel_enrollment(self) -> None:
        with self._lock:
            self._enrollment_name = None
            self._enrollment_features.clear()

    def face_lost(self) -> None:
        """Reset recognition stability after the person leaves camera view."""
        with self._lock:
            self._candidate = ""
            self._candidate_frames = 0

    def forget(self, name: str) -> bool:
        """Delete one person's local face template."""
        target = name.strip().casefold()
        with self._lock:
            existing = next(
                (saved for saved in self._templates if saved.casefold() == target),
                None,
            )
            if existing is None:
                return False
            del self._templates[existing]
            self._last_announced.pop(existing, None)
            self._save_database()
        self._status(f"Forgot face profile for {existing}.")
        return True

    def observe(self, frame, face_row) -> FaceRecognition:
        """Extract a feature, update enrollment, or recognise the face."""
        if self._engine is None or face_row is None:
            return FaceRecognition()
        with self._lock:
            if not self._templates and self._enrollment_name is None:
                return FaceRecognition()
        try:
            aligned = self._engine.alignCrop(frame, face_row)
            feature = np.asarray(self._engine.feature(aligned), dtype=np.float32)
            feature = self._normalise(feature.reshape(-1).copy())
        except Exception:  # noqa: BLE001
            log.exception("SFace feature extraction failed")
            return FaceRecognition()

        with self._lock:
            if self._enrollment_name:
                return self._collect_enrollment(feature)
            name, score = self._best_match(feature)
            known = bool(name and score >= self._threshold)
            label = name if known else "Unknown"
            announce = self._update_stability(label, known)

        if announce:
            self._on_recognized(label, score)
        return FaceRecognition(name=label, score=score, known=known)

    def _collect_enrollment(self, feature: np.ndarray) -> FaceRecognition:
        name = self._enrollment_name or ""
        self._enrollment_features.append(feature)
        count = len(self._enrollment_features)
        if count >= self._sample_target:
            average = self._normalise(
                np.mean(np.stack(self._enrollment_features, axis=0), axis=0)
            )
            self._templates[name] = average
            self._enrollment_name = None
            self._enrollment_features.clear()
            self._candidate = ""
            self._candidate_frames = 0
            self._save_database()
            self._status(f"Face profile saved for {name}.")
            return FaceRecognition(name=name, score=1.0, known=True)
        return FaceRecognition(
            name=name,
            score=1.0,
            known=True,
            enrolling=True,
            enrollment_progress=count,
            enrollment_total=self._sample_target,
        )

    def _best_match(self, feature: np.ndarray) -> tuple[str, float]:
        if not self._templates:
            return "", 0.0
        name, score = max(
            (
                (saved_name, float(np.dot(feature, saved_feature)))
                for saved_name, saved_feature in self._templates.items()
            ),
            key=lambda item: item[1],
        )
        return name, max(-1.0, min(1.0, score))

    def _update_stability(self, label: str, known: bool) -> bool:
        if not known:
            self._candidate = ""
            self._candidate_frames = 0
            return False
        if label == self._candidate:
            self._candidate_frames += 1
        else:
            self._candidate = label
            self._candidate_frames = 1
        if self._candidate_frames != self._stable_frames:
            return False
        now = self._clock()
        last = self._last_announced.get(label, -1e9)
        if now - last < self._greeting_cooldown:
            return False
        self._last_announced[label] = now
        return True

    def _load_database(self) -> None:
        if not self._database_path.is_file():
            return
        try:
            data = json.loads(self._database_path.read_text(encoding="utf-8"))
            people = data.get("people", {}) if isinstance(data, dict) else {}
            loaded: dict[str, np.ndarray] = {}
            for name, values in people.items():
                vector = np.asarray(values, dtype=np.float32).reshape(-1)
                if vector.size > 0 and np.isfinite(vector).all():
                    loaded[str(name)] = self._normalise(vector)
            self._templates = loaded
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            log.exception("Could not read face template database")
            self._templates = {}

    def _save_database(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": 1,
            "model": self._model_path.name,
            "people": {
                name: [round(float(value), 8) for value in vector]
                for name, vector in sorted(self._templates.items())
            },
        }
        temporary = self._database_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self._database_path)

    @staticmethod
    def _normalise(vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8:
            raise ValueError("empty face embedding")
        return (vector / norm).astype(np.float32, copy=False)
