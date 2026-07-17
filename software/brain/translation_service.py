"""
brain/translation_service.py
============================
Translation on top of the provider system. Supports one-shot, bidirectional and
continuous translation. Returns translated TEXT only - speech/audio is handled
elsewhere. Automatic language detection is a future hook (detect() returns None
for now, and callers pass explicit languages).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.logger import get_logger

from .brain_config import TaskKind
from .brain_result import BrainResult
from .provider_registry import GenerationRequest

log = get_logger("brain.translation")


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    source_lang: str = "auto"
    target_lang: str = "en"


class TranslationService:
    """Builds translation prompts and delegates generation to a callable that
    runs a provider (injected by the Brain Manager, keeping this decoupled)."""

    def __init__(self, generate: "callable", prompt: str | None = None) -> None:
        # generate: (GenerationRequest, TaskKind) -> BrainResult
        self._generate = generate
        self._prompt = prompt or (
            "You are a translation engine. Translate the user's text into "
            "{target}. Output only the translation, nothing else.")

    def translate(self, req: TranslationRequest) -> BrainResult:
        system = self._prompt.format(target=req.target_lang)
        instruction = req.text
        if req.source_lang and req.source_lang != "auto":
            system += f" The source language is {req.source_lang}."
        gen = GenerationRequest(
            system_prompt=system,
            messages=({"role": "user", "content": instruction},),
            temperature=0.2, max_tokens=1024,
            metadata={"target_lang": req.target_lang,
                      "source_lang": req.source_lang})
        result = self._generate(gen, TaskKind.TRANSLATION)
        # Surface the translated text in the dedicated field.
        if result.success:
            return BrainResult(
                response=result.response, provider=result.provider,
                confidence=result.confidence,
                processing_time=result.processing_time, tokens=result.tokens,
                translation=result.response, success=True,
                metadata={**result.metadata, "target_lang": req.target_lang})
        return result

    def detect_language(self, text: str) -> str | None:
        """Future hook for automatic language detection. Returns None for now."""
        return None
