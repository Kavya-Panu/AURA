// =============================================================================
//  core/Constants.h
// -----------------------------------------------------------------------------
//  FIXED constants defined by the firmware / protocol specification — values
//  that are NOT tuning knobs. If a value describes "how the firmware talks to
//  the laptop" or "what this build IS", it belongs here. If it describes "how
//  the robot looks or feels" and might be adjusted, it belongs in Config.h.
//
//  Data only: constexpr values and string literals. No classes, no functions.
// =============================================================================
#pragma once

#include <cstdint>

namespace aura {
namespace fw {

// -----------------------------------------------------------------------------
//  Firmware identity.
// -----------------------------------------------------------------------------
constexpr char     name[]      = "AURA-Face";
constexpr char     version[]   = "2.0.0";
constexpr uint32_t protocolId  = 2;          // serial protocol revision

// -----------------------------------------------------------------------------
//  Serial link parameters (fixed by the protocol, matched on the laptop side).
// -----------------------------------------------------------------------------
namespace serial {
    // 16 kHz, mono, 16-bit PCM is transported as Base64 lines. 921600 baud
    // provides enough headroom for real-time microphone and speaker audio.
    constexpr uint32_t baudRate      = 921600;
    constexpr char     lineEnding    = '\n';    // commands are newline-terminated
    constexpr uint16_t rxBufferSize  = 1024;    // command or one audio frame
    constexpr uint32_t readTimeoutMs = 20;      // non-blocking read budget
}  // namespace serial

// -----------------------------------------------------------------------------
//  Default timeouts / intervals fixed by the firmware (milliseconds).
// -----------------------------------------------------------------------------
namespace timeout {
    constexpr uint32_t heartbeatMs   = 5000;    // expect traffic within this
    constexpr uint32_t bootSplashMs  = 1800;    // AURA logo hold on power-up
    constexpr uint32_t commandAckMs  = 50;      // reply window after a command
}  // namespace timeout

// -----------------------------------------------------------------------------
//  Command vocabulary — the exact ASCII tokens accepted over serial.
//  These are the contract with the laptop HAL and must not drift. The parser
//  accepts both the space-separated form (verbs + args) and the compact
//  single-token emotion form used by the existing brain.
// -----------------------------------------------------------------------------
namespace cmd {
    // Verbs (space-separated form: "FACE HAPPY", "LOOK LEFT", "BRIGHTNESS 180").
    constexpr char face[]       = "FACE";
    constexpr char look[]       = "LOOK";
    constexpr char blink[]      = "BLINK";
    constexpr char book[]       = "BOOK";
    constexpr char sleep[]      = "SLEEP";
    constexpr char wake[]       = "WAKE";
    constexpr char brightness[] = "BRIGHTNESS";
    constexpr char ping[]       = "PING";

    // Arguments for LOOK.
    constexpr char argLeft[]    = "LEFT";
    constexpr char argRight[]   = "RIGHT";
    constexpr char argUp[]      = "UP";
    constexpr char argDown[]    = "DOWN";
    constexpr char argCenter[]  = "CENTER";
    constexpr char argStop[]    = "STOP";      // e.g. "BOOK STOP"
}  // namespace cmd

// -----------------------------------------------------------------------------
//  Emotion tokens — the single-word identifiers exchanged with the laptop.
//  One-to-one with aura::Emotion (see core/Types.h). Order matches that enum so
//  a lookup table can pair them index-for-index.
// -----------------------------------------------------------------------------
namespace token {
    constexpr char neutral[]   = "NEUTRAL";
    constexpr char happy[]     = "HAPPY";
    constexpr char excited[]   = "EXCITED";
    constexpr char sad[]       = "SAD";
    constexpr char angry[]     = "ANGRY";
    constexpr char surprised[] = "SURPRISED";
    constexpr char confused[]  = "CONFUSED";
    constexpr char curious[]   = "CURIOUS";
    constexpr char love[]      = "LOVE";
    constexpr char thinking[]  = "THINK";
    constexpr char listening[] = "LISTEN";
    constexpr char searching[] = "SEARCH";
    constexpr char worried[]   = "WORRIED";
    constexpr char celebrate[] = "CELEBRATE";
    constexpr char sleepy[]    = "SLEEPY";
    constexpr char sleep[]     = "SLEEP";
    constexpr char error[]     = "ERROR";
}  // namespace token

// -----------------------------------------------------------------------------
//  Reply strings — fixed responses the firmware sends back to the laptop.
// -----------------------------------------------------------------------------
namespace reply {
    constexpr char ok[]   = "OK";
    constexpr char error[] = "ERR";
    constexpr char pong[] = "PONG";
}  // namespace reply

}  // namespace fw
}  // namespace aura
