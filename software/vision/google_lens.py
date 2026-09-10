"""Optional Google Web Detection adapter for Lens-like visual identification.

The camera image is sent only when the user explicitly asks a visual question.
If Google credentials or the network are unavailable, callers can fall back to
AURA's existing local MediaPipe detector without affecting voice operation.
"""
from __future__ import annotations

import html
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger("vision.google_lens")


@dataclass(frozen=True)
class LensSource:
    title: str
    url: str


@dataclass(frozen=True)
class LensResult:
    text: str
    success: bool
    candidates: tuple[str, ...] = ()
    sources: tuple[LensSource, ...] = ()
    confidence: float = 0.0
    error: str = ""


class GoogleLensService:
    """Identify a camera object using Google Cloud Vision Web Detection."""

    _GENERIC = {
        "object", "item", "product", "device", "electronic device",
        "electronics", "technology", "hardware", "computer hardware",
        "gadget", "tool", "machine", "material property", "material",
        "plastic", "dairy", "glass", "metal", "wood", "packaging",
        "container", "food", "drink", "beverage",
        "white", "black", "red", "green", "blue", "yellow", "orange",
        "pink", "purple", "brown", "grey", "gray", "color", "colour",
    }

    # These describe the scene around an object rather than the item the user
    # is asking AURA to identify. Google often gives a visible hand a
    # best-guess-label boost, even when its web entities correctly contain the
    # bottle, circuit board, tool, etc. being held.
    _SCENE_CONTEXT = {
        "arm", "body", "finger", "fingernail", "gesture", "hand",
        "human", "human body", "human hand", "palm", "person", "skin",
        "thumb", "wrist",
    }

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        *,
        max_results: int = 10,
        client_factory: Callable[[], object] | None = None,
        image_factory: Callable[..., object] | None = None,
    ) -> None:
        self._credentials_path = str(credentials_path or "").strip()
        self._max_results = max(3, min(20, int(max_results)))
        self._client_factory = client_factory
        self._image_factory = image_factory
        self._client = None
        self._lock = threading.RLock()
        self._checked = False
        self._error = ""

    @property
    def ready(self) -> bool:
        return self._ensure_client()

    @property
    def error(self) -> str:
        return self._error

    def identify(self, question: str, frame) -> LensResult:
        """Search one camera frame and return one concise spoken answer."""
        if frame is None:
            return LensResult(
                "I cannot get a camera image right now.",
                False,
                error="camera frame unavailable",
            )
        # A covered/uninitialised camera can still receive confident colour
        # labels from the API. There is no object evidence in a flat image.
        import numpy as np
        pixels = np.asarray(frame)
        if (pixels.ndim != 3 or pixels.size == 0
                or min(pixels.shape[:2]) < 8
                or float(pixels.reshape(-1, pixels.shape[-1]).std(axis=0).max()) < 2.0):
            return LensResult(
                "I cannot see enough detail to identify that. Uncover the camera and hold the object in good light.",
                False,
                error="camera image has insufficient detail",
            )
        if not self._ensure_client():
            return LensResult(
                "Google image search is not configured, so I will use local vision.",
                False,
                error=self._error or "Google Vision unavailable",
            )

        try:
            content = self._encode_frame(frame)
            image = self._image_factory(content=content)
            with self._lock:
                if hasattr(self._client, "annotate_image"):
                    response = self._client.annotate_image(
                        request={
                            "image": image,
                            "features": self._combined_features(),
                        }
                    )
                else:
                    # Small fake clients and older integrations retain the
                    # original Web Detection-only interface.
                    response = self._client.web_detection(
                        image=image,
                        max_results=self._max_results,
                    )
            response_error = str(
                getattr(getattr(response, "error", None), "message", "") or ""
            ).strip()
            if response_error:
                raise RuntimeError(response_error)
            return self._answer(
                question,
                response.web_detection,
                labels=getattr(response, "label_annotations", None) or [],
                localized_objects=(
                    getattr(response, "localized_object_annotations", None) or []
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._error = f"Google Web Detection failed: {exc}"
            log.warning("%s", self._error)
            return LensResult(
                "The web image search failed, so I will use local vision.",
                False,
                error=self._error,
            )

    def _ensure_client(self) -> bool:
        with self._lock:
            if self._client is not None:
                return True
            if self._checked:
                return False
            self._checked = True
            try:
                if self._client_factory is not None:
                    self._client = self._client_factory()
                    self._image_factory = self._image_factory or (
                        lambda **kwargs: kwargs["content"]
                    )
                    return True

                from google.cloud import vision

                credentials = None
                if self._credentials_path:
                    from google.oauth2 import service_account

                    expanded = os.path.expandvars(self._credentials_path)
                    path = Path(expanded).expanduser().resolve()
                    if not path.is_file():
                        raise RuntimeError(f"credential file not found: {path}")
                    credentials = service_account.Credentials.from_service_account_file(
                        str(path)
                    )
                elif not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                    # Do not let Google's broad ADC search delay every AURA
                    # startup when this optional feature has not been set up.
                    raise RuntimeError(
                        "credentials not configured; set google_vision_credentials"
                    )
                self._client = vision.ImageAnnotatorClient(credentials=credentials)
                self._image_factory = vision.Image
                return True
            except Exception as exc:  # noqa: BLE001
                self._client = None
                self._error = f"Google Vision unavailable: {exc}"
                log.info("%s", self._error)
                return False

    def _combined_features(self) -> list[object]:
        """Use complementary official Vision features in one network call."""
        from google.cloud import vision

        return [
            vision.Feature(
                type_=vision.Feature.Type.WEB_DETECTION,
                max_results=self._max_results,
            ),
            vision.Feature(
                type_=vision.Feature.Type.LABEL_DETECTION,
                max_results=self._max_results,
                model="builtin/latest",
            ),
            vision.Feature(
                type_=vision.Feature.Type.OBJECT_LOCALIZATION,
                max_results=self._max_results,
                model="builtin/latest",
            ),
        ]

    def _answer(
        self,
        question: str,
        web,
        *,
        labels=(),
        localized_objects=(),
    ) -> LensResult:
        best_labels = [
            self._clean_text(getattr(item, "label", ""))
            for item in (getattr(web, "best_guess_labels", None) or [])
        ]
        entities = [
            (
                self._clean_text(getattr(item, "description", "")),
                float(getattr(item, "score", 0.0) or 0.0),
            )
            for item in (getattr(web, "web_entities", None) or [])
        ]
        pages = [
            LensSource(
                self._clean_page_title(getattr(item, "page_title", "")),
                str(getattr(item, "url", "") or "").strip(),
            )
            for item in (getattr(web, "pages_with_matching_images", None) or [])
        ]
        pages = [item for item in pages if item.title or item.url]

        ranked: list[tuple[float, str]] = []
        for label in best_labels:
            if label:
                ranked.append((1.10 + self._specificity(label), label))
        for description, score in entities:
            if description:
                ranked.append(
                    (
                        min(1.0, max(0.0, score)) * 1.20
                        + self._specificity(description),
                        description,
                    )
                )
        for page in pages[:5]:
            candidate = self._candidate_from_title(page.title)
            if candidate:
                ranked.append((0.60 + self._specificity(candidate), candidate))
        for item in labels:
            description = self._clean_text(getattr(item, "description", ""))
            score = float(getattr(item, "score", 0.0) or 0.0)
            if description:
                ranked.append(
                    (0.40 + min(1.0, max(0.0, score)) * 1.40 + self._specificity(description), description)
                )
        for item in localized_objects:
            description = self._clean_text(getattr(item, "name", ""))
            score = float(getattr(item, "score", 0.0) or 0.0)
            if description:
                ranked.append(
                    (0.60 + min(1.0, max(0.0, score)) * 1.50 + self._specificity(description), description)
                )

        deduplicated: list[tuple[float, str]] = []
        seen: set[str] = set()
        for score, value in sorted(ranked, key=lambda item: item[0], reverse=True):
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append((score, value))

        specific = [item for item in deduplicated if item[1].casefold() not in self._GENERIC]
        object_question = bool(
            re.search(
                r"\b(?:this|that|object|item|holding|hold|in\s+my\s+hand)\b",
                question,
                re.IGNORECASE,
            )
        )
        if object_question:
            without_context = [
                item for item in specific if not self._is_scene_context(item[1])
            ]
            specific = without_context
        # Materials, colours, and hands alone do not identify a held object.
        # Falling back to those labels caused answers such as 'a plastic'.
        choices = specific
        if not choices:
            return LensResult(
                "I searched the image, but I could not find a reliable match.",
                False,
                sources=tuple(pages[:3]),
                error="Google returned no useful web entities",
            )

        choices = self._boost_agreement(choices)
        score, candidate = choices[0]
        confidence = max(0.25, min(0.98, score / 2.0))
        if confidence < 0.56 or self._looks_like_brand_only(candidate):
            return LensResult(
                "I cannot identify that reliably. Hold the object closer, keep it centred, and try again.",
                False,
                tuple(value for _rank, value in choices[:5]),
                tuple(pages[:3]),
                confidence,
                "Google results did not contain a reliable object match",
            )
        prefix = "That appears to be" if confidence >= 0.62 else "The closest web match is"
        return LensResult(
            f"{prefix} {self._spoken_candidate(candidate)}.",
            True,
            tuple(value for _rank, value in choices[:5]),
            tuple(pages[:3]),
            confidence,
        )

    @classmethod
    def _specificity(cls, value: str) -> float:
        normalized = value.casefold().strip()
        if normalized in cls._GENERIC:
            return -0.9
        words = value.split()
        bonus = min(0.35, max(0, len(words) - 1) * 0.07)
        if re.search(r"\d", value):
            bonus += 0.20
        if re.search(r"\b(?:model|series|board|module|kit|pro|mini|nano|uno)\b", value, re.I):
            bonus += 0.15
        return bonus

    @classmethod
    def _boost_agreement(
        cls,
        choices: list[tuple[float, str]],
    ) -> list[tuple[float, str]]:
        """Reward labels that agree across web, label, and object results."""
        token_sets = [cls._identity_tokens(value) for _score, value in choices]
        boosted: list[tuple[float, str]] = []
        for index, (score, value) in enumerate(choices):
            agreement = 0
            for other_index, other_tokens in enumerate(token_sets):
                if index == other_index or not token_sets[index] or not other_tokens:
                    continue
                if token_sets[index] & other_tokens:
                    agreement += 1
            boosted.append((score + min(0.45, agreement * 0.15), value))
        return sorted(boosted, key=lambda item: item[0], reverse=True)

    @classmethod
    def _identity_tokens(cls, value: str) -> set[str]:
        ignored = {
            "and", "for", "the", "with", "plastic", "glass", "metal",
            "product", "item", "object",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.casefold())
            if len(token) > 2 and token not in ignored
        }

    @staticmethod
    def _looks_like_brand_only(value: str) -> bool:
        """Reject a lone retailer/brand token as an object identification."""
        cleaned = value.strip()
        return bool("&" in cleaned and len(cleaned.split()) <= 3)

    @classmethod
    def _is_scene_context(cls, value: str) -> bool:
        normalized = value.casefold().strip()
        if normalized in cls._SCENE_CONTEXT:
            return True
        words = set(re.findall(r"[a-z]+", normalized))
        return bool(words) and words <= {
            "adult", "arm", "body", "child", "finger", "hand", "human",
            "male", "female", "palm", "person", "skin", "thumb", "wrist",
        }

    @staticmethod
    def _clean_text(value: str) -> str:
        text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
        return " ".join(text.split()).strip(" -|:;,.")

    @classmethod
    def _clean_page_title(cls, value: str) -> str:
        return cls._clean_text(value)

    @classmethod
    def _candidate_from_title(cls, title: str) -> str:
        if not title:
            return ""
        value = re.sub(
            r"^(?:buy|shop|official|amazon(?:\.co\.uk)?\s*[:|-]?)\s+",
            "",
            title,
            flags=re.IGNORECASE,
        )
        # Remove a trailing website/store name while retaining hyphenated model names.
        parts = re.split(r"\s+[|–—]\s+", value, maxsplit=1)
        value = parts[0].strip()
        if len(value) > 90 or value.casefold() in cls._GENERIC:
            return ""
        return value

    @staticmethod
    def _spoken_name(value: str) -> str:
        return value.rstrip(".!?")

    @classmethod
    def _spoken_candidate(cls, value: str) -> str:
        """Make category labels natural without altering product/model names."""
        cleaned = cls._spoken_name(value)
        if not cleaned:
            return "an unknown object"
        # Google category labels such as "Plastic bottle" are title-cased even
        # though they are common nouns. Product/model names usually contain a
        # digit, acronym, trademark-like punctuation, or multiple capitals.
        product_like = bool(
            re.search(r"\d|[&+®™]", cleaned)
            or sum(1 for word in cleaned.split() if word[:1].isupper()) >= 2
        )
        if product_like:
            return cleaned
        common = cleaned.casefold()
        article = "an" if common[:1] in "aeiou" else "a"
        return f"{article} {common}"

    @staticmethod
    def _encode_frame(frame) -> bytes:
        import cv2

        height, width = frame.shape[:2]
        if width > 1280:
            scale = 1280.0 / width
            frame = cv2.resize(
                frame,
                (1280, max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 90],
        )
        if not ok:
            raise RuntimeError("camera frame could not be encoded")
        return encoded.tobytes()
