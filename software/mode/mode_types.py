"""
mode/mode_types.py
==================
The vocabulary of the Mode System: the :class:`ModeType` enum and one typed
parameter dataclass per mode that needs configuration.

Mode vs State (the whole point of this module):
    * STATE  = what AURA is *doing* right now (LISTENING, THINKING...) - changes
      constantly, owned by the core StateMachine.
    * MODE   = what *kind of robot* AURA is *being* (FOCUS, TRANSLATION...) -
      changes rarely and only on explicit request, owned by the ModeManager.

Parameters are typed dataclasses (no loose dicts) so a future Focus/Translation
module gets autocomplete and validation for free, while still allowing a raw
dict override at request time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class ModeType(Enum):
    """Every kind of robot AURA can be. Add a member here + one registry entry
    to introduce a new mode (see mode_registry.py)."""
    NORMAL = auto()
    FOCUS = auto()
    TRANSLATION = auto()
    TEACHER = auto()
    QUIZ = auto()
    HOMEWORK = auto()
    PRESENTATION = auto()
    ASSISTANT = auto()
    MEMORY = auto()
    NIGHT = auto()
    CHARGING = auto()
    MAINTENANCE = auto()


# ---------------------------------------------------------------------------
#  Typed parameter payloads. Defaults are the mode's "resting" configuration;
#  callers override any field when requesting the mode.
# ---------------------------------------------------------------------------
class ModeParams:
    """Marker base class so ``params`` can be typed as ``ModeParams | None``."""


@dataclass
class FocusParams(ModeParams):
    duration_minutes: int = 120        # "focus mode" default = 2 h
    break_minutes: int = 5
    phone_detection: bool = True
    disable_chatter: bool = True


@dataclass
class TranslationParams(ModeParams):
    source_language: str = "English"
    target_language: str = "Spanish"
    continuous: bool = True            # keeps translating until "Aura stop"
    bidirectional: bool = True


@dataclass
class TeacherParams(ModeParams):
    subject: str = ""
    difficulty: str = "beginner"
    lesson: int = 0
    progress: float = 0.0             # 0..1


@dataclass
class QuizParams(ModeParams):
    subject: str = ""
    score: int = 0
    questions_remaining: int = 10
    difficulty: str = "beginner"


@dataclass
class HomeworkParams(ModeParams):
    assignment: str = ""
    subject: str = ""
    deadline: str | None = None       # ISO date string
    progress: float = 0.0


@dataclass
class PresentationParams(ModeParams):
    title: str = ""
    slide_count: int = 0
    current_slide: int = 0


@dataclass
class NightParams(ModeParams):
    brightness: float = 0.2           # 0..1 reduced brightness
    quiet: bool = True


@dataclass
class ChargingParams(ModeParams):
    show_battery: bool = True
    limited_interaction: bool = True


@dataclass
class GenericParams(ModeParams):
    """Fallback for modes without a dedicated dataclass (NORMAL, ASSISTANT,
    MEMORY, MAINTENANCE). ``extra`` keeps arbitrary custom data."""
    extra: dict[str, Any] = field(default_factory=dict)


# Factory map: mode -> callable returning fresh default params. Registered in
# mode_registry.py, kept here so params + factories live together.
DEFAULT_PARAM_FACTORIES: dict[ModeType, Callable[[], ModeParams]] = {
    ModeType.NORMAL:       GenericParams,
    ModeType.FOCUS:        FocusParams,
    ModeType.TRANSLATION:  TranslationParams,
    ModeType.TEACHER:      TeacherParams,
    ModeType.QUIZ:         QuizParams,
    ModeType.HOMEWORK:     HomeworkParams,
    ModeType.PRESENTATION: PresentationParams,
    ModeType.ASSISTANT:    GenericParams,
    ModeType.MEMORY:       GenericParams,
    ModeType.NIGHT:        NightParams,
    ModeType.CHARGING:     ChargingParams,
    ModeType.MAINTENANCE:  GenericParams,
}


def make_default_params(mode: ModeType) -> ModeParams:
    """Return a fresh default parameter object for ``mode``."""
    return DEFAULT_PARAM_FACTORIES.get(mode, GenericParams)()
