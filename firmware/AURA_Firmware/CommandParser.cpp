// =============================================================================
//  communication/CommandParser.cpp
// -----------------------------------------------------------------------------
//  Table-driven command interpretation. parseCommand() normalises the line
//  (trim + uppercase), splits it into a verb and an argument, looks the verb up
//  in a dispatch table, and calls the matching handler. Handlers validate their
//  argument and translate it into a single FaceController call. Anything that
//  doesn't match yields a clear ParseStatus and a matching ERR_* reply.
// =============================================================================
#include "CommandParser.h"
#include <stdlib.h>

namespace aura {

namespace {
// ---- header-free string helpers (internal linkage) -------------------------

inline char upperCh(char c) {
    return (c >= 'a' && c <= 'z') ? static_cast<char>(c - 'a' + 'A') : c;
}

inline bool eq(const char* a, const char* b) {
    while (*a && *b) { if (*a != *b) return false; ++a; ++b; }
    return *a == *b;
}

inline size_t copyInto(char* dst, const char* src, size_t cap) {
    size_t n = 0;
    while (src[n] != '\0' && n < cap - 1) { dst[n] = src[n]; ++n; }
    dst[n] = '\0';
    return n;
}

// Parse an unsigned integer; false if empty or contains a non-digit.
bool parseUInt(const char* s, uint32_t& out) {
    if (*s == '\0') return false;
    uint32_t v = 0;
    for (const char* p = s; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9') return false;
        v = v * 10 + static_cast<uint32_t>(*p - '0');
        if (v > 1000000u) return false;             // sane bound
    }
    out = v;
    return true;
}

// Parse exactly two normalized floats: "x y", each in [-1, 1].
bool parseGazePair(const char* s, float& x, float& y) {
    if (s == nullptr || *s == '\0') return false;
    char* end = nullptr;
    x = strtof(s, &end);
    if (end == s) return false;
    while (*end == ' ' || *end == '\t') ++end;
    if (*end == '\0') return false;
    char* tail = nullptr;
    y = strtof(end, &tail);
    if (tail == end) return false;
    while (*tail == ' ' || *tail == '\t') ++tail;
    if (*tail != '\0') return false;
    // These comparisons also reject NaN.
    return x >= -1.0f && x <= 1.0f && y >= -1.0f && y <= 1.0f;
}

// Emotion vocabulary: protocol tokens plus friendly aliases (THINK/THINKING…).
struct EmoEntry { const char* key; Emotion value; };
constexpr EmoEntry kEmotions[] = {
    {fw::token::neutral,   Emotion::Neutral},
    {fw::token::happy,     Emotion::Happy},
    {fw::token::excited,   Emotion::Excited},
    {fw::token::sad,       Emotion::Sad},
    {fw::token::angry,     Emotion::Angry},
    {fw::token::surprised, Emotion::Surprised},
    {fw::token::confused,  Emotion::Confused},
    {fw::token::curious,   Emotion::Curious},
    {fw::token::love,      Emotion::Love},
    {fw::token::thinking,  Emotion::Thinking},   // "THINK"
    {"THINKING",           Emotion::Thinking},   // alias
    {fw::token::listening, Emotion::Listening},  // "LISTEN"
    {"LISTENING",          Emotion::Listening},  // alias
    {fw::token::searching, Emotion::Searching},  // "SEARCH"
    {"SEARCHING",          Emotion::Searching},  // alias
    {fw::token::worried,   Emotion::Worried},
    {fw::token::celebrate, Emotion::Celebrate},
    {fw::token::sleepy,    Emotion::Sleepy},
    {fw::token::sleep,     Emotion::Sleep},
    {fw::token::error,     Emotion::Error},
};

bool lookupEmotion(const char* arg, Emotion& out) {
    for (const auto& e : kEmotions) {
        if (eq(arg, e.key)) { out = e.value; return true; }
    }
    return false;
}

// Reply strings the caller sends back. OK/PONG come from Constants; the detailed
// ERR_* strings are this parser's diagnostic vocabulary.
constexpr char kReplyOk[]        = "OK";
constexpr char kErrUnknown[]     = "ERR_UNKNOWN_COMMAND";
constexpr char kErrInvalidArg[]  = "ERR_INVALID_ARGUMENT";
constexpr char kErrMissingParam[] = "ERR_MISSING_PARAMETER";
constexpr char kErrNotReady[]    = "ERR_NOT_READY";

const char* emotionName(Emotion e) {
    for (const auto& x : kEmotions) {
        if (x.value == e) return x.key;   // returns the first (canonical) token
    }
    return "?";
}

const char* sceneName(SceneManager::Scene s) {
    switch (s) {
        case SceneManager::Scene::Boot:     return "BOOT";
        case SceneManager::Scene::Idle:     return "IDLE";
        case SceneManager::Scene::Book:     return "BOOK";
        case SceneManager::Scene::Shutdown: return "SHUTDOWN";
    }
    return "?";
}
}  // namespace

// ---- setup ------------------------------------------------------------------

void CommandParser::begin() { reset(); }

void CommandParser::reset() {
    _work[0] = '\0';
    _replyBuf[0] = '\0';
    _lastReply = "";
}

// ---- parsing ----------------------------------------------------------------

ParseStatus CommandParser::parseCommand(const char* command) {
    _lastReply = kReplyOk;                         // default; handlers may change

    if (_fc == nullptr) {                          // not wired up yet
        _lastReply = kErrNotReady;
        return ParseStatus::UnknownCommand;
    }
    if (command == nullptr) {
        _lastReply = kErrUnknown;
        return ParseStatus::UnknownCommand;
    }

    // Normalise: skip leading blanks, uppercase, copy into the work buffer.
    while (*command == ' ' || *command == '\t') ++command;
    size_t n = 0;
    for (; command[n] != '\0' && n < kMaxCommandLen - 1; ++n) {
        _work[n] = upperCh(command[n]);
    }
    _work[n] = '\0';
    while (n > 0 && (_work[n - 1] == ' ' || _work[n - 1] == '\t')) {
        _work[--n] = '\0';                         // trim trailing blanks
    }
    if (n == 0) {                                  // empty line
        _lastReply = kErrUnknown;
        return ParseStatus::UnknownCommand;
    }

    // Split into verb + argument (argument is the trimmed remainder).
    char* sp = _work;
    while (*sp != '\0' && *sp != ' ') ++sp;
    const char* verb = _work;
    const char* arg  = "";
    if (*sp != '\0') {
        *sp = '\0';
        arg = sp + 1;
        while (*arg == ' ') ++arg;
    }

    // Dispatch. The verb→handler table is function-local so it can name the
    // private Handler type and take the address of private member functions.
    struct VerbEntry { const char* key; Handler fn; };
    static const VerbEntry kVerbs[] = {
        {fw::cmd::face,       &CommandParser::cmdFace},
        {fw::cmd::look,       &CommandParser::cmdLook},
        {"GAZE",              &CommandParser::cmdGaze},
        {fw::cmd::blink,      &CommandParser::cmdBlink},
        {"DOUBLE_BLINK",      &CommandParser::cmdDoubleBlink},
        {fw::cmd::sleep,      &CommandParser::cmdSleep},
        {fw::cmd::wake,       &CommandParser::cmdWake},
        {fw::cmd::book,       &CommandParser::cmdBook},
        {"TIMER",            &CommandParser::cmdTimer},
        {"BOOT",              &CommandParser::cmdBoot},
        {"SHUTDOWN",          &CommandParser::cmdShutdown},
        {fw::cmd::brightness, &CommandParser::cmdBrightness},
        {fw::cmd::ping,       &CommandParser::cmdPing},
        {"STATUS",            &CommandParser::cmdStatus},
        {"RESET",             &CommandParser::cmdReset},
    };

    for (const auto& v : kVerbs) {
        if (eq(verb, v.key)) {
            const ParseStatus st = (this->*(v.fn))(arg);
            switch (st) {
                case ParseStatus::Ok:               break;   // reply already set
                case ParseStatus::UnknownCommand:   _lastReply = kErrUnknown;      break;
                case ParseStatus::InvalidArgument:  _lastReply = kErrInvalidArg;   break;
                case ParseStatus::MissingParameter: _lastReply = kErrMissingParam; break;
            }
            return st;
        }
    }

    // Direct emotion aliases are accepted for easy Arduino Serial Monitor tests
    // and compatibility with the original AURA protocol. Both forms work:
    //     FACE HAPPY
    //     HAPPY
    if (*arg == '\0') {
        Emotion directEmotion;
        if (lookupEmotion(verb, directEmotion)) {
            _fc->setEmotion(directEmotion);
            _lastReply = kReplyOk;
            return ParseStatus::Ok;
        }
    }

    _lastReply = kErrUnknown;
    return ParseStatus::UnknownCommand;
}

// ---- handlers ---------------------------------------------------------------

ParseStatus CommandParser::cmdFace(const char* arg) {
    if (*arg == '\0') return ParseStatus::MissingParameter;
    Emotion e;
    if (!lookupEmotion(arg, e)) return ParseStatus::InvalidArgument;
    _fc->setEmotion(e);
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdLook(const char* arg) {
    if (*arg == '\0') return ParseStatus::MissingParameter;
    if      (eq(arg, fw::cmd::argLeft))   _fc->lookLeft();
    else if (eq(arg, fw::cmd::argRight))  _fc->lookRight();
    else if (eq(arg, fw::cmd::argUp))     _fc->lookUp();
    else if (eq(arg, fw::cmd::argDown))   _fc->lookDown();
    else if (eq(arg, fw::cmd::argCenter)) _fc->lookCenter();
    else return ParseStatus::InvalidArgument;
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdGaze(const char* arg) {
    if (*arg == '\0') return ParseStatus::MissingParameter;
    float x = 0.0f;
    float y = 0.0f;
    if (!parseGazePair(arg, x, y)) return ParseStatus::InvalidArgument;
    _fc->lookAt(x, y);
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdBlink(const char*) {
    _fc->blink();
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdDoubleBlink(const char*) {
    _fc->doubleBlink();
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdSleep(const char*) {
    _fc->sleep();
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdWake(const char*) {
    _fc->wake();
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdBook(const char* arg) {
    if (*arg == '\0') return ParseStatus::MissingParameter;
    if      (eq(arg, "START"))            _fc->startBookMode();
    else if (eq(arg, fw::cmd::argStop))   _fc->stopBookMode(true);
    else return ParseStatus::InvalidArgument;
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdTimer(const char* arg) {
    if (*arg == '\0') return ParseStatus::MissingParameter;
    if (eq(arg, "STOP")) {
        _fc->stopCountdown();
        return ParseStatus::Ok;
    }
    if (eq(arg, "ALERT") || (arg[0] == 'A' && arg[1] == 'L'
            && arg[2] == 'E' && arg[3] == 'R' && arg[4] == 'T'
            && arg[5] == ' ')) {
        const char* kind = arg[5] == ' ' ? arg + 6 : "TIMER";
        _fc->showCountdownAlert(*kind ? kind : "TIMER");
        return ParseStatus::Ok;
    }
    if (!(arg[0] == 'S' && arg[1] == 'T' && arg[2] == 'A'
            && arg[3] == 'R' && arg[4] == 'T' && arg[5] == ' ')) {
        return ParseStatus::InvalidArgument;
    }
    const char* value = arg + 6;
    char* end = nullptr;
    const unsigned long seconds = strtoul(value, &end, 10);
    if (end == value || seconds == 0 || seconds > 2678400UL) {
        return ParseStatus::InvalidArgument;
    }
    while (*end == ' ') ++end;
    const char* kind = *end ? end : "TIMER";
    _fc->startCountdown(static_cast<uint32_t>(seconds), kind);
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdBoot(const char*) {
    _fc->startBootAnimation();
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdShutdown(const char*) {
    _fc->startShutdownAnimation();
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdBrightness(const char* arg) {
    if (*arg == '\0') return ParseStatus::MissingParameter;
    uint32_t v;
    if (!parseUInt(arg, v) || v > 255) return ParseStatus::InvalidArgument;
    _fc->setBrightness(static_cast<uint8_t>(v));
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdPing(const char*) {
    _lastReply = fw::reply::pong;                  // "PONG"
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdStatus(const char*) {
    buildStatusReply();
    _lastReply = _replyBuf;
    return ParseStatus::Ok;
}

ParseStatus CommandParser::cmdReset(const char*) {
    _fc->reset();
    return ParseStatus::Ok;
}

// ---- helpers ----------------------------------------------------------------

void CommandParser::buildStatusReply() {
    // "STATUS EMOTION=<name> SCENE=<name>" assembled without allocation.
    size_t pos = 0;
    auto append = [&](const char* s) {
        while (*s != '\0' && pos < kReplyLen - 1) _replyBuf[pos++] = *s++;
    };
    append("STATUS EMOTION=");
    append(emotionName(_fc->currentEmotion()));
    append(" SCENE=");
    append(sceneName(_fc->currentScene()));
    _replyBuf[pos] = '\0';
    (void)copyInto;   // copyInto kept available for future handlers
}

}  // namespace aura
