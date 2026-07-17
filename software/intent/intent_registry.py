"""
intent/intent_registry.py
=========================
IntentDefinition + the default registry containing a matching definition for
every voice intent in AURA_COMMAND_SPEC.md. Adding a new intent = one
``registry.register(IntentDefinition(...))`` call; the matcher needs no edits.

Pattern phrases are written in NORMALISED form (lowercase, no apostrophes:
"whats", "im", "lets", "youre").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .intent_exceptions import IntentRegistryError
from .intent_types import Intent


@dataclass(frozen=True)
class IntentDefinition:
    """Static matching + parameter contract for one intent.

    Attributes:
        intent: The intent this definition matches.
        phrases: Normalised example phrasings (matched by token overlap).
        keywords: Token *classes* that strongly signal this intent.
        param_names: Parameters this intent consumes (others are dropped).
        soft_required: Missing -> clarification question (defaults exist).
        hard_required: Missing -> clarification question (no default).
        modes: Mode names where this intent is valid (None = ANY).
        target_mode: Mode this intent enters, if any (entry intents are
            slightly penalised when already in their target mode).
        boost_params: Extracted params that raise this intent's score.
        penalize_params: Extracted params that LOWER this intent's score
            (e.g. a subject present makes "study X" teaching, not focus).
        response_hint: Short phrasing hint for downstream speech.
    """
    intent: Intent
    phrases: tuple[str, ...]
    keywords: frozenset[str] = frozenset()
    param_names: tuple[str, ...] = ()
    soft_required: tuple[str, ...] = ()
    hard_required: tuple[str, ...] = ()
    modes: frozenset[str] | None = None
    target_mode: str | None = None
    boost_params: tuple[str, ...] = ()
    penalize_params: tuple[str, ...] = ()
    response_hint: str = ""


class IntentRegistry:
    """Intent -> IntentDefinition store."""

    def __init__(self) -> None:
        self._defs: dict[Intent, IntentDefinition] = {}

    def register(self, definition: IntentDefinition) -> None:
        if definition.intent in self._defs:
            raise IntentRegistryError("Duplicate intent definition",
                                      {"intent": definition.intent.value})
        self._defs[definition.intent] = definition

    def get(self, intent: Intent) -> IntentDefinition | None:
        return self._defs.get(intent)

    def definitions(self) -> list[IntentDefinition]:
        return list(self._defs.values())


def _kw(*classes: str) -> frozenset[str]:
    return frozenset(classes)


def _m(*modes: str) -> frozenset[str]:
    return frozenset(modes)


def build_default_registry() -> IntentRegistry:      # noqa: PLR0915
    """Registry with a definition for every spec voice intent."""
    r = IntentRegistry()
    D, I = IntentDefinition, Intent

    # ---------------- Greeting ----------------
    r.register(D(I.GREET, ("hi", "hello", "hey", "good to see you", "hey there"),
                 _kw("hello"), response_hint="greet warmly"))
    r.register(D(I.GREET_MORNING, ("good morning", "morning"),
                 response_hint="bright morning greeting"))
    r.register(D(I.GREET_NIGHT, ("good night", "goodnight", "im going to sleep",
                                 "night night"),
                 target_mode="NIGHT", response_hint="soft goodnight"))
    # ---------------- Assistant ----------------
    r.register(D(I.START_ASSISTANT, ("assistant mode", "be my assistant",
                                     "i need help with something"),
                 target_mode="ASSISTANT"))
    r.register(D(I.GET_WEATHER, ("whats the weather", "will it rain",
                                 "weather today", "hows the weather",
                                 "weather in"),
                 _kw("weather"), param_names=("location", "query")))
    r.register(D(I.SET_TIMER, ("set a timer", "timer for", "start a timer",
                               "set a timer for 10 minutes"),
                 _kw("timer"), param_names=("timer_seconds",),
                 hard_required=("timer_seconds",),
                 boost_params=("timer_seconds",)))
    r.register(D(I.SET_REMINDER, ("remind me", "set a reminder",
                                  "remind me to drink water at 5 pm"),
                 _kw("remind"),
                 param_names=("reminder_time", "reminder_text"),
                 hard_required=("reminder_text",),
                 soft_required=("reminder_time",),
                 boost_params=("reminder_text",)))
    r.register(D(I.CALCULATE, ("calculate", "whats 15% of 240",
                               "what is 12 times 9", "compute"),
                 _kw("calculate"), param_names=("expression",),
                 hard_required=("expression",), boost_params=("expression",)))
    r.register(D(I.GET_CALENDAR, ("whats on my calendar",
                                  "do i have anything today",
                                  "my schedule", "calendar"),
                 param_names=("query",)))
    r.register(D(I.CONTROL_MUSIC, ("play music", "play some music",
                                   "play focus music", "stop the music",
                                   "pause the music"),
                 _kw("music"), param_names=("query",)))
    r.register(D(I.WEB_SEARCH, ("search for", "look up", "google",
                                "search the internet for"),
                 _kw("search"), param_names=("query",),
                 hard_required=("query",)))
    # ---------------- Focus ----------------
    r.register(D(I.START_FOCUS,
                 ("start focus", "focus mode", "lets study", "help me focus",
                  "study mode", "start studying", "i need to concentrate",
                  "lets focus", "time to study", "begin focus",
                  "help me focus for 2 hours", "i want to focus"),
                 _kw("focus"),
                 param_names=("duration_minutes", "break_minutes",
                              "phone_detection"),
                 soft_required=("duration_minutes",),
                 target_mode="FOCUS",
                 penalize_params=("subject",),
                 response_hint="entering focus mode"))
    r.register(D(I.SET_FOCUS_DURATION,
                 ("focus for", "study for", "make it", "set duration to",
                  "change the duration to", "make it 90 minutes"),
                 param_names=("duration_minutes",),
                 hard_required=("duration_minutes",),
                 modes=_m("FOCUS"), boost_params=("duration_minutes",)))
    r.register(D(I.PAUSE_FOCUS, ("pause focus", "hold on", "pause the timer",
                                 "pause the session"),
                 modes=_m("FOCUS")))
    r.register(D(I.RESUME_FOCUS, ("resume focus", "lets continue",
                                  "back to work", "continue studying"),
                 modes=_m("FOCUS")))
    r.register(D(I.START_BREAK, ("i need a break", "break time",
                                 "lets take a break", "pause for a bit"),
                 _kw("break"), param_names=("break_minutes",),
                 modes=_m("FOCUS")))
    r.register(D(I.STOP_FOCUS, ("stop focus", "im done studying",
                                "end the session", "exit focus",
                                "end focus mode"),
                 modes=_m("FOCUS"), response_hint="ending focus session"))
    r.register(D(I.FOCUS_STATUS, ("how much time left", "time remaining",
                                  "focus status", "how long left",
                                  "hows my session"),
                 modes=_m("FOCUS")))
    # ---------------- Translation ----------------
    r.register(D(I.START_TRANSLATION,
                 ("translate everything", "translate everything i say",
                  "start translation", "be our interpreter",
                  "start translating", "translation mode",
                  "act as an interpreter", "translate english to japanese",
                  "translate hindi to english", "translate to", "translate"),
                 _kw("translate"),
                 param_names=("source_language", "target_language",
                              "bidirectional", "continuous",
                              "auto_detect_language"),
                 soft_required=("target_language",),
                 target_mode="TRANSLATION",
                 boost_params=("target_language",),
                 response_hint="starting live translation"))
    r.register(D(I.SET_TRANSLATION_LANGUAGE,
                 ("change target language", "now translate to", "switch to",
                  "change the language to", "translate to french instead"),
                 param_names=("target_language", "source_language"),
                 hard_required=("target_language",),
                 modes=_m("TRANSLATION"), boost_params=("target_language",)))
    r.register(D(I.SET_AUTODETECT_LANGUAGE,
                 ("detect language automatically", "auto detect language",
                  "figure out the language", "detect the language"),
                 modes=_m("TRANSLATION")))
    r.register(D(I.PAUSE_TRANSLATION, ("pause translation",
                                       "pause translating"),
                 modes=_m("TRANSLATION")))
    r.register(D(I.RESUME_TRANSLATION, ("resume translation",
                                        "resume translating",
                                        "continue translation"),
                 modes=_m("TRANSLATION")))
    r.register(D(I.STOP_TRANSLATION, ("stop translation", "stop translating",
                                      "were done translating",
                                      "end translation"),
                 modes=_m("TRANSLATION"),
                 response_hint="ending translation"))
    # ---------------- Teacher ----------------
    r.register(D(I.START_TEACHING,
                 ("teach me", "i want to learn", "help me learn",
                  "i want to study", "tutor me", "explain", "teach me about",
                  "i want to learn about"),
                 _kw("teach", "learn"),
                 param_names=("subject", "topic", "difficulty"),
                 soft_required=("subject",),
                 target_mode="TEACHER",
                 boost_params=("subject", "topic"),
                 response_hint="starting a lesson"))
    r.register(D(I.EXPLAIN, ("explain this", "what does this mean",
                             "explain that again", "what is this"),
                 _kw("explain"), param_names=("query", "topic"),
                 modes=_m("TEACHER")))
    r.register(D(I.SIMPLIFY, ("simplify that", "explain it more simply",
                              "i dont get it", "make it simpler"),
                 _kw("simplify"), modes=_m("TEACHER")))
    r.register(D(I.GIVE_EXAMPLES, ("give me examples", "show me an example",
                                   "like what", "give an example"),
                 _kw("example"), modes=_m("TEACHER")))
    r.register(D(I.TEACHER_ASK, ("ask me questions", "test my understanding",
                                 "check if i got it", "quiz my understanding"),
                 modes=_m("TEACHER")))
    r.register(D(I.TEACHER_CONTINUE, ("continue", "next part", "go on",
                                      "keep going"),
                 modes=_m("TEACHER")))
    r.register(D(I.TEACHER_REPEAT, ("repeat that", "say that again",
                                    "one more time"),
                 modes=_m("TEACHER")))
    r.register(D(I.TEACHER_SUMMARIZE, ("summarize", "give me the summary",
                                       "recap the lesson", "sum it up"),
                 _kw("summarize"), modes=_m("TEACHER")))
    r.register(D(I.STOP_TEACHING, ("stop teaching", "im done learning",
                                   "exit teacher mode", "end the lesson"),
                 modes=_m("TEACHER")))
    # ---------------- Homework ----------------
    r.register(D(I.START_HOMEWORK,
                 ("help with homework", "help me with my homework",
                  "homework mode", "i have an assignment", "im stuck",
                  "help me solve this", "help me with my assignment"),
                 _kw("homework"),
                 param_names=("subject", "assignment", "deadline"),
                 target_mode="HOMEWORK",
                 response_hint="opening homework help"))
    r.register(D(I.HOMEWORK_HELP, ("help me with this problem",
                                   "im stuck on question", "im stuck on this",
                                   "help me solve this one"),
                 param_names=("query",), modes=_m("HOMEWORK")))
    r.register(D(I.CHECK_ANSWER, ("check my answer", "is this right",
                                  "did i get it correct", "is my answer right"),
                 _kw("check", "answer"), param_names=("query",),
                 modes=_m("HOMEWORK")))
    r.register(D(I.EXPLAIN_STEPS, ("explain step by step",
                                   "walk me through it", "show the steps",
                                   "step by step please"),
                 param_names=("query",), modes=_m("HOMEWORK", "TEACHER")))
    r.register(D(I.ALT_SOLUTION, ("show another way", "another method",
                                  "solve it differently",
                                  "is there another way"),
                 param_names=("query",), modes=_m("HOMEWORK")))
    r.register(D(I.STOP_HOMEWORK, ("stop homework", "im done with homework",
                                   "exit homework mode"),
                 modes=_m("HOMEWORK")))
    # ---------------- Quiz ----------------
    r.register(D(I.START_QUIZ, ("quiz me", "test me", "start a quiz",
                                "ask me questions", "lets do a quiz",
                                "quiz me on biology", "give me a test"),
                 _kw("quiz"),
                 param_names=("subject", "difficulty", "question_count"),
                 target_mode="QUIZ",
                 boost_params=("subject",),
                 response_hint="starting a quiz"))
    r.register(D(I.QUIZ_NEXT, ("next question", "skip this one",
                               "skip", "next one"),
                 modes=_m("QUIZ")))
    r.register(D(I.QUIZ_HINT, ("give me a hint", "i need a clue",
                               "hint please", "a little help"),
                 _kw("hint"), modes=_m("QUIZ")))
    r.register(D(I.QUIZ_REPEAT, ("repeat the question", "say that again",
                                 "what was the question"),
                 modes=_m("QUIZ")))
    r.register(D(I.QUIZ_SCORE, ("whats my score", "how am i doing",
                                "current score", "my points"),
                 _kw("score"), modes=_m("QUIZ")))
    r.register(D(I.END_QUIZ, ("end quiz", "stop the quiz", "im finished",
                              "end the quiz"),
                 modes=_m("QUIZ"), response_hint="ending the quiz"))
    # ---------------- Presentation ----------------
    r.register(D(I.START_PRESENTATION, ("presentation mode",
                                        "help me rehearse",
                                        "start my slides",
                                        "presentation practice"),
                 param_names=("title", "slide_count"),
                 target_mode="PRESENTATION"))
    r.register(D(I.SLIDE_NEXT, ("next slide",), modes=_m("PRESENTATION")))
    r.register(D(I.SLIDE_PREV, ("previous slide", "go back a slide"),
                 modes=_m("PRESENTATION")))
    r.register(D(I.PRESENTATION_TIMER, ("start the timer",
                                        "how much time do i have",
                                        "give me cues"),
                 param_names=("timer_seconds",), modes=_m("PRESENTATION")))
    r.register(D(I.STOP_PRESENTATION, ("stop presentation",
                                       "im done presenting"),
                 modes=_m("PRESENTATION")))
    # ---------------- Memory ----------------
    r.register(D(I.MEMORY_REMEMBER, ("remember that", "note this down",
                                     "remember this", "remember my exam is on friday"),
                 _kw("remember"),
                 param_names=("memory_value", "memory_key"),
                 hard_required=("memory_value",),
                 boost_params=("memory_value",)))
    r.register(D(I.MEMORY_FORGET, ("forget that", "forget what i told you",
                                   "delete that memory", "forget about"),
                 _kw("forget"), param_names=("memory_key", "query")))
    r.register(D(I.MEMORY_RECALL, ("what do you remember",
                                   "what did i tell you",
                                   "what do you know about my"),
                 param_names=("query",)))
    r.register(D(I.STUDY_HISTORY, ("show my study history",
                                   "how much did i study this week",
                                   "study history", "my study sessions"),
                 param_names=("query",)))
    r.register(D(I.WEAK_SUBJECTS, ("what are my weak subjects",
                                   "where should i improve",
                                   "my weakest subjects"),))
    r.register(D(I.ACHIEVEMENTS, ("show my achievements", "my streaks",
                                  "my badges", "what are my achievements"),))
    r.register(D(I.DAILY_PROGRESS, ("how did i do today", "todays progress",
                                    "daily summary", "my progress today"),))
    # ---------------- Social ----------------
    r.register(D(I.SOCIAL_THANKS, ("thank you", "thanks", "thanks a lot",
                                   "thank you so much"),
                 _kw("thanks"), response_hint="warm acknowledgement"))
    r.register(D(I.SOCIAL_HOWAREYOU, ("how are you", "you good",
                                      "hows it going"),))
    r.register(D(I.SOCIAL_JOKE, ("tell me a joke", "make me laugh",
                                 "say something funny"),
                 _kw("joke")))
    r.register(D(I.SOCIAL_IDENTITY, ("who are you", "what are you",
                                     "introduce yourself"),))
    r.register(D(I.SOCIAL_COMPLIMENT, ("youre awesome", "good job",
                                       "i love you", "youre the best",
                                       "youre amazing", "well done"),
                 _kw("praise"), response_hint="delighted thanks"))
    r.register(D(I.SOCIAL_INSULT, ("i hate you", "stupid aura", "bad aura",
                                   "youre useless", "youre dumb"),
                 _kw("insult"), response_hint="calm, non-defensive"))
    r.register(D(I.SOCIAL_TIRED, ("im tired", "im exhausted",
                                  "im so tired"),
                 _kw("tired"), response_hint="gentle concern"))
    r.register(D(I.SOCIAL_STRESSED, ("im stressed", "im overwhelmed",
                                     "this is too much"),
                 _kw("stressed"), response_hint="calm support"))
    r.register(D(I.SOCIAL_BORED, ("im bored", "this is boring"),
                 _kw("bored"), response_hint="suggest an activity"))
    r.register(D(I.SOCIAL_MOTIVATE, ("motivate me", "give me a push",
                                     "encourage me", "i need motivation"),
                 _kw("motivate")))
    # ---------------- Robot controls ----------------
    r.register(D(I.LOOK_AT_USER, ("look at me", "pay attention",
                                  "look here"),))
    r.register(D(I.FOLLOW_USER, ("follow me", "track me", "keep watching me"),
                 _kw("follow")))
    r.register(D(I.STOP_FOLLOW, ("stop following", "look away",
                                 "stop tracking me"),))
    r.register(D(I.SEARCH_LOOK, ("look around", "scan the room"),))
    r.register(D(I.FACE_GESTURE, ("blink", "wink", "wink at me"),))
    r.register(D(I.MUTE_SPEECH, ("be quiet", "shush", "silence",
                                 "shut up", "stop talking"),
                 _kw("quiet"), response_hint="immediate silence"))
    r.register(D(I.VOLUME_UP, ("louder", "speak up", "volume up"),
                 _kw("louder")))
    r.register(D(I.VOLUME_DOWN, ("quieter", "lower your voice",
                                 "volume down", "speak softer"),
                 _kw("quieter")))
    # ---------------- System ----------------
    r.register(D(I.ENTER_NIGHT, ("go to sleep", "night mode",
                                 "sleep mode"),
                 target_mode="NIGHT"))
    r.register(D(I.WAKE_SYSTEM, ("wake up", "aura wake up", "rise and shine"),
                 _kw("wake")))
    r.register(D(I.SHUTDOWN, ("shut down", "power off", "turn off",
                              "turn yourself off"),))
    r.register(D(I.RESTART, ("restart", "reboot", "restart yourself"),))
    r.register(D(I.CANCEL, ("cancel", "never mind", "stop that",
                            "forget it"),
                 response_hint="cancelled"))
    r.register(D(I.ENTER_NORMAL, ("normal mode", "back to normal",
                                  "reset mode", "return to normal"),
                 target_mode="NORMAL"))
    r.register(D(I.HELP, ("help", "what can you do", "what can you help with",
                          "list your features"),))
    r.register(D(I.BATTERY_STATUS, ("battery", "how much battery",
                                    "are you charged", "battery level"),
                 _kw("battery")))
    # ---------------- Developer ----------------
    r.register(D(I.DEV_STATE, ("status report", "whats your state",
                               "system status"),))
    r.register(D(I.DEV_VERSION, ("version", "what version are you"),))
    r.register(D(I.DEV_DEBUG, ("debug on", "enable debug", "debug off"),))
    return r


#: Shared default registry (built once at import; cheap and immutable in use).
registry = build_default_registry()
