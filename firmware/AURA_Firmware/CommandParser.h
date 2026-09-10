// =============================================================================
//  communication/CommandParser.h
// -----------------------------------------------------------------------------
//  Translates incoming text commands into FaceController calls. That is its
//  entire job.
//
//  CommandParser interprets a single already-assembled line (e.g. "FACE HAPPY",
//  "BRIGHTNESS 180", "PING") and invokes the matching high-level FaceController
//  method. It does NOT touch the serial port, draw anything, access hardware,
//  implement animation, or know any AI logic. It never sends a reply itself —
//  it returns a status and exposes the text the caller should send back, so the
//  transport (SerialManager) and the interpretation (this class) stay separate.
//
//  Dispatch is table-driven (verb → handler), input is normalised
//  (trimmed, case-insensitive), arguments are validated, and malformed input
//  yields a clear error status rather than a crash.
//
//  Allowed dependencies (and no others): FaceController.h, Types.h, Constants.h.
//  (String comes transitively via FaceController.h's include chain.)
// =============================================================================
#pragma once

#include "Types.h"
#include "Constants.h"
#include "FaceController.h"

namespace aura {

/// Result of interpreting one command line.
enum class ParseStatus : uint8_t {
    Ok,
    UnknownCommand,
    InvalidArgument,
    MissingParameter,
};

class CommandParser {
public:
    CommandParser() = default;

    // ---- setup --------------------------------------------------------------

    /// Reset internal state. (No hardware to initialise.)
    void begin();

    /// Bind the FaceController this parser drives. Must be called before
    /// parseCommand(); until then, commands return a safe error.
    void registerFaceController(FaceController& controller) { _fc = &controller; }

    /// Clear any pending reply state.
    void reset();

    // ---- parsing ------------------------------------------------------------

    /// Interpret one command line (newline already stripped) and invoke the
    /// matching FaceController method. Returns the outcome; the reply string to
    /// send is available via lastReply().
    ParseStatus parseCommand(const char* command);

    /// Convenience overload matching the classic Arduino signature.
    ParseStatus parseCommand(const String& command) {
        return parseCommand(command.c_str());
    }

    /// The text the caller should send in response to the last parseCommand():
    /// "OK", "PONG", a STATUS line, or one of the ERR_* strings. Valid until the
    /// next parseCommand().
    const char* lastReply() const { return _lastReply; }

private:
    using Handler = ParseStatus (CommandParser::*)(const char* arg);

    // Verb handlers (one per command). Each validates its argument and calls
    // FaceController, returning a status.
    ParseStatus cmdFace(const char* arg);
    ParseStatus cmdLook(const char* arg);
    ParseStatus cmdGaze(const char* arg);
    ParseStatus cmdBlink(const char* arg);
    ParseStatus cmdDoubleBlink(const char* arg);
    ParseStatus cmdSleep(const char* arg);
    ParseStatus cmdWake(const char* arg);
    ParseStatus cmdBook(const char* arg);
    ParseStatus cmdTimer(const char* arg);
    ParseStatus cmdBoot(const char* arg);
    ParseStatus cmdShutdown(const char* arg);
    ParseStatus cmdBrightness(const char* arg);
    ParseStatus cmdPing(const char* arg);
    ParseStatus cmdStatus(const char* arg);
    ParseStatus cmdReset(const char* arg);

    void buildStatusReply();

    // Fixed capacities (no dynamic allocation).
    static constexpr size_t kMaxCommandLen = fw::serial::rxBufferSize;  // 128
    static constexpr size_t kReplyLen      = 64;

    FaceController* _fc = nullptr;
    char        _work[kMaxCommandLen] = {};   ///< normalised copy for tokenising
    char        _replyBuf[kReplyLen]  = {};   ///< STATUS reply is built here
    const char* _lastReply = "";
};

}  // namespace aura
