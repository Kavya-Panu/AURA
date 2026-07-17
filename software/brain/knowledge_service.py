"""
brain/knowledge_service.py
==========================
Task-shaping for knowledge/teaching requests: general questions, electronics,
programming, mathematics, study explanations, summaries, worked examples, and
step-by-step teaching. It classifies a question into a TaskKind (so the selector
can route it) and augments the system prompt with a subject hint. It does not
call providers itself - the Brain Manager runs generation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .brain_config import TaskKind


@dataclass(frozen=True)
class KnowledgeRequest:
    question: str
    subject: str = "general"        # general|electronics|programming|math|study
    style: str = "explain"          # explain|summary|example|stepwise


_SUBJECT_HINTS = {
    "electronics": "Focus on electronics and circuits; use correct units.",
    "programming": "Give correct, idiomatic code and explain briefly.",
    "math": "Show the steps and reasoning; keep arithmetic correct.",
    "study": "Explain in a way that helps a student learn and remember.",
    "general": "",
}

_STYLE_HINTS = {
    "explain": "Explain clearly and concisely.",
    "summary": "Summarise the key points briefly.",
    "example": "Give a concrete worked example.",
    "stepwise": "Teach step by step, one step at a time.",
}


class KnowledgeService:
    """Classifies a knowledge request and shapes its prompt."""

    def classify(self, req: KnowledgeRequest) -> TaskKind:
        if req.style == "summary":
            return TaskKind.SUMMARY
        if req.style in ("stepwise", "example") or req.subject in (
                "math", "electronics", "programming", "study"):
            return TaskKind.TEACHING
        # Long/complex questions get routed to reasoning-capable providers.
        if len(req.question.split()) > 40:
            return TaskKind.COMPLEX_REASONING
        return TaskKind.SIMPLE_QA

    def augment_prompt(self, base_prompt: str, req: KnowledgeRequest) -> str:
        subject = _SUBJECT_HINTS.get(req.subject, "")
        style = _STYLE_HINTS.get(req.style, "")
        extra = " ".join(p for p in (subject, style) if p)
        return f"{base_prompt} {extra}".strip() if extra else base_prompt
