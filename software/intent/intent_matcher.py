"""
intent/intent_matcher.py
========================
Deterministic scoring of an utterance against every IntentDefinition.

Score per definition = best phrase coverage (token classes) + keyword boost
+ extracted-parameter boost, shaped by mode: out-of-mode intents are strongly
penalised, in-mode intents get a small bonus, and entry intents are slightly
penalised inside their own target mode (so "focus for 90 minutes" inside FOCUS
prefers SET_FOCUS_DURATION over re-entering).
"""
from __future__ import annotations

from dataclasses import dataclass

from .intent_registry import IntentDefinition, IntentRegistry
from .synonym_dictionary import token_class
from .utils import clamp, is_subsequence, overlap_ratio

_PHRASE_WEIGHT = 0.62
_KEYWORD_WEIGHT = 0.28
_PARAM_BOOST = 0.10        # per boost param present (capped)
_PARAM_BOOST_CAP = 0.20
_PARAM_PENALTY = 0.30    # per penalize param present
_ORDER_BONUS = 0.08        # phrase tokens appear in order
_EXACT_SCORE = 0.98
_MODE_MATCH_BONUS = 0.06
_MODE_MISMATCH_FACTOR = 0.40
_ENTRY_IN_TARGET_FACTOR = 0.72


@dataclass(frozen=True)
class MatchCandidate:
    """One scored intent hypothesis."""
    definition: IntentDefinition
    score: float


class IntentMatcher:
    """Scores utterances against the registry. Stateless per call."""

    def __init__(self, registry: IntentRegistry) -> None:
        self._entries: list[tuple[IntentDefinition,
                                  list[tuple[list[str], set[str]]]]] = []
        for definition in registry.definitions():
            phrases = []
            for phrase in definition.phrases:
                toks = [token_class(t) for t in phrase.split()]
                phrases.append((toks, set(toks)))
            self._entries.append((definition, phrases))

    def match(self, tokens: list[str], params: dict, mode: str
              ) -> list[MatchCandidate]:
        """Return candidates sorted by descending score."""
        classes = [token_class(t) for t in tokens]
        class_set = set(classes)
        out: list[MatchCandidate] = []

        for definition, phrases in self._entries:
            best = 0.0
            for phrase_list, phrase_set in phrases:
                cover = overlap_ratio(class_set, phrase_set)
                if cover <= 0:
                    continue
                score = cover
                if cover >= 0.999 and is_subsequence(phrase_list, classes):
                    score += _ORDER_BONUS
                    if len(class_set) <= len(phrase_set) + 1:
                        score = _EXACT_SCORE / _PHRASE_WEIGHT  # exact hit
                best = max(best, score)
            if best <= 0:
                continue

            kw_frac = (len(definition.keywords & class_set)
                       / len(definition.keywords)) if definition.keywords else 0.0
            boost = min(_PARAM_BOOST_CAP,
                        _PARAM_BOOST * sum(1 for p in definition.boost_params
                                           if p in params))
            penalty = _PARAM_PENALTY * sum(
                1 for p in definition.penalize_params if p in params)
            score = clamp(best * _PHRASE_WEIGHT
                          + kw_frac * _KEYWORD_WEIGHT + boost - penalty,
                          0.0, 1.0)

            # Mode shaping.
            if definition.modes is not None:
                if mode in definition.modes:
                    score = clamp(score + _MODE_MATCH_BONUS, 0.0, 1.0)
                else:
                    score *= _MODE_MISMATCH_FACTOR
            if definition.target_mode is not None and mode == definition.target_mode:
                score *= _ENTRY_IN_TARGET_FACTOR

            if score > 0.05:
                out.append(MatchCandidate(definition, round(score, 4)))

        out.sort(key=lambda c: -c.score)
        return out
