"""
intent/intent_engine.py
=======================
The Intent Engine facade: text in, IntentResult out. Nothing else.

Pipeline per utterance:
    parse -> mode-aware generic resolution ("stop"/"pause"/...) ->
    scored matching -> mode fallbacks (free speech in TRANSLATION/QUIZ) ->
    confidence banding -> parameter validation + inheritance ->
    clarification / fallback -> IntentResult.

Fully deterministic (dictionaries + regex + arithmetic): typical processing is
well under 1 ms, comfortably inside the 50 ms budget.
"""
from __future__ import annotations

from typing import Any

from core.logger import get_logger

from .clarification import question_for_low_confidence, question_for_missing
from .confidence import ConfidenceLevel, level
from .fallback import unknown_result
from .intent_context import IntentContext
from .intent_exceptions import IntentParseError
from .intent_matcher import IntentMatcher
from .intent_parser import IntentParser
from .intent_registry import IntentRegistry, registry as default_registry
from .intent_result import IntentResult
from .intent_types import Intent
from .synonym_dictionary import FILLER, token_class
from .validator import validate

log = get_logger("intent.engine")

_GENERIC_CONF = 0.95

# Mode-aware resolution of bare generic verbs (spec: "Never guess. Use mode.").
_STOP_BY_MODE: dict[str, Intent] = {
    "FOCUS": Intent.STOP_FOCUS,
    "TRANSLATION": Intent.STOP_TRANSLATION,
    "QUIZ": Intent.END_QUIZ,
    "TEACHER": Intent.STOP_TEACHING,
    "HOMEWORK": Intent.STOP_HOMEWORK,
    "PRESENTATION": Intent.STOP_PRESENTATION,
}
_PAUSE_BY_MODE: dict[str, Intent] = {
    "FOCUS": Intent.PAUSE_FOCUS,
    "TRANSLATION": Intent.PAUSE_TRANSLATION,
}
_RESUME_BY_MODE: dict[str, Intent] = {
    "FOCUS": Intent.RESUME_FOCUS,
    "TRANSLATION": Intent.RESUME_TRANSLATION,
    "TEACHER": Intent.TEACHER_CONTINUE,
}
_NEXT_BY_MODE: dict[str, Intent] = {
    "QUIZ": Intent.QUIZ_NEXT,
    "PRESENTATION": Intent.SLIDE_NEXT,
    "TEACHER": Intent.TEACHER_CONTINUE,
}
_REPEAT_BY_MODE: dict[str, Intent] = {
    "QUIZ": Intent.QUIZ_REPEAT,
    "TEACHER": Intent.TEACHER_REPEAT,
}

_AMBIGUITY_GAP = 0.06


class IntentEngine:
    """Converts natural language into structured IntentResults."""

    def __init__(self, registry: IntentRegistry | None = None) -> None:
        self._registry = registry or default_registry
        self._parser = IntentParser()
        self._matcher = IntentMatcher(self._registry)

    # ------------------------------------------------------------------ API
    def process(self,
                text: str,
                current_mode: Any = None,
                conversation_context: IntentContext | None = None,
                session_state: dict[str, Any] | None = None) -> IntentResult:
        """Classify one utterance. Never raises on user speech."""
        mode = self._mode_name(current_mode)
        try:
            parsed = self._parser.parse(text)
        except IntentParseError:
            return unknown_result(text)

        # 1) Mode-aware generic verbs ("aura stop" etc.) - highest certainty.
        generic = self._resolve_generic(parsed.tokens, mode)
        if generic is not None:
            result = self._build(generic, _GENERIC_CONF, parsed,
                                 conversation_context)
            self._remember(conversation_context, result)
            return result

        # 2) Continuous modes: speech WITHOUT a wake word is content, not a
        #    command (spec 10.7: the session was wake-word initiated; only an
        #    explicit wake-worded command interrupts the loop).
        if not parsed.had_wake_word:
            if mode == "TRANSLATION":
                result = IntentResult(
                    intent=Intent.TRANSLATE_UTTERANCE, confidence=0.95,
                    parameters={"query": parsed.normalized},
                    response_hint="translate this utterance",
                    raw_text=parsed.raw)
                self._remember(conversation_context, result)
                return result
            if mode == "QUIZ":
                result = IntentResult(
                    intent=Intent.QUIZ_ANSWER, confidence=0.9,
                    parameters={"query": parsed.normalized},
                    response_hint="grade this answer",
                    raw_text=parsed.raw)
                self._remember(conversation_context, result)
                return result

        # 3) Scored matching.
        candidates = self._matcher.match(parsed.tokens, parsed.params, mode)
        top = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None

        # 4) Wake-worded but unmatched inside continuous modes.
        if (top is None or top.score < 0.55):
            if mode == "TRANSLATION":
                result = IntentResult(
                    intent=Intent.TRANSLATE_UTTERANCE, confidence=0.9,
                    parameters={"query": parsed.normalized},
                    response_hint="translate this utterance",
                    raw_text=parsed.raw)
                self._remember(conversation_context, result)
                return result
            if mode == "QUIZ":
                result = IntentResult(
                    intent=Intent.QUIZ_ANSWER, confidence=0.85,
                    parameters={"query": parsed.normalized},
                    response_hint="grade this answer",
                    raw_text=parsed.raw)
                self._remember(conversation_context, result)
                return result

        if top is None:
            return unknown_result(text)

        band = level(top.score)
        if band is ConfidenceLevel.UNKNOWN:
            return unknown_result(text, confidence=top.score)

        if band is ConfidenceLevel.CLARIFY:
            # Weak/ambiguous: never act. If the intent is clear-ish but a key
            # parameter is missing, ask for THAT (more useful); otherwise
            # confirm the intent itself.
            params = self._final_params(top.definition, parsed,
                                        conversation_context)
            missing = [p for p in (*top.definition.hard_required,
                                   *top.definition.soft_required)
                       if p not in params]
            if missing:
                question = question_for_missing(top.definition.intent,
                                                missing[0])
            else:
                question = question_for_low_confidence(top.definition.intent)
                if second is not None and (top.score - second.score) < _AMBIGUITY_GAP:
                    question += (" Or did you mean to "
                                 + question_for_low_confidence(
                                     second.definition.intent)[16:])
            return IntentResult(
                intent=top.definition.intent, confidence=top.score,
                parameters=params, missing_parameters=missing,
                clarification_needed=True,
                clarification_question=question,
                response_hint="confirm before acting",
                raw_text=parsed.raw)

        if band is ConfidenceLevel.EXECUTE_LOG:
            log.info("executing %s at confidence %.2f (log band)",
                     top.definition.intent.value, top.score)

        result = self._build(top.definition.intent, top.score, parsed,
                             conversation_context)
        self._remember(conversation_context, result)
        return result

    # ------------------------------------------------------------- internals
    @staticmethod
    def _mode_name(mode: Any) -> str:
        if mode is None:
            return "NORMAL"
        return getattr(mode, "name", str(mode)).upper()

    def _resolve_generic(self, tokens: list[str], mode: str) -> Intent | None:
        """Bare 'stop/pause/resume/next/repeat' resolve by CURRENT MODE."""
        meaningful = {token_class(t) for t in tokens} - FILLER
        if not meaningful:
            return None
        tables = (("stop", _STOP_BY_MODE), ("pause", _PAUSE_BY_MODE),
                  ("resume", _RESUME_BY_MODE), ("next", _NEXT_BY_MODE),
                  ("repeat", _REPEAT_BY_MODE))
        for verb, table in tables:
            if meaningful <= {verb, "question", "slide", "session", "focus"} \
                    and verb in meaningful and mode in table:
                return table[mode]
        if meaningful == {"stop"}:        # bare stop outside any mode
            return Intent.CANCEL
        return None

    def _final_params(self, definition, parsed,
                      context: IntentContext | None) -> dict[str, Any]:
        """Filter to declared params, validate, apply topic->subject aliasing
        and context inheritance (e.g. quiz inherits last taught subject)."""
        raw = {k: v for k, v in parsed.params.items()
               if k in definition.param_names}
        # Teaching-family: a free topic satisfies a missing subject.
        if ("subject" in definition.param_names
                and "subject" not in raw and "topic" in parsed.params):
            raw["subject"] = parsed.params["topic"]
        cleaned = validate(definition.intent, raw)
        # Session awareness: inherit the last subject when still missing.
        if ("subject" in definition.param_names and "subject" not in cleaned
                and context is not None):
            inherited = context.last_value("subject")
            if inherited:
                cleaned["subject"] = inherited
        return cleaned

    def _build(self, intent: Intent, confidence: float, parsed,
               context: IntentContext | None) -> IntentResult:
        definition = self._registry.get(intent)
        params = (self._final_params(definition, parsed, context)
                  if definition else dict(parsed.params))
        hint = definition.response_hint if definition else ""

        missing: list[str] = []
        question = ""
        if definition is not None:
            for name in (*definition.hard_required, *definition.soft_required):
                if name not in params and name not in missing:
                    missing.append(name)
            if missing:
                question = question_for_missing(intent, missing[0])

        return IntentResult(
            intent=intent, confidence=confidence, parameters=params,
            missing_parameters=missing,
            clarification_needed=bool(missing),
            clarification_question=question,
            response_hint=hint, raw_text=parsed.raw)

    @staticmethod
    def _remember(context: IntentContext | None, result: IntentResult) -> None:
        if context is not None and result.intent is not Intent.UNKNOWN:
            context.add(result.intent, result.parameters)
