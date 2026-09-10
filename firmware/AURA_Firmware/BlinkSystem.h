// =============================================================================
//  face/BlinkSystem.h
// -----------------------------------------------------------------------------
//  Decides how open the eyes should be over time — and nothing else.
//
//  BlinkSystem is a self-contained, non-blocking timing state machine. It runs
//  on its own random schedule, can be told to blink now (single or double), can
//  be held forcibly open or closed, and produces a single normalised output:
//      eyeOpenAmount()  ->  1.0 = fully open, 0.0 = fully closed
//  It NEVER draws, never knows about the display, emotions, serial, or robot
//  behaviour. Whoever renders the eyes multiplies this value into eye openness.
//
//  Allowed dependencies (and no others): core/Types.h, core/Config.h.
//  Deliberately does NOT include <Arduino.h>: randomness comes from a tiny
//  built-in PRNG and timing is driven by an injected delta time, so the whole
//  class is deterministic and unit-testable on any host.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"

namespace aura {

class BlinkSystem {
public:
    /// Forced-hold override, independent of the blink schedule.
    enum class Hold : uint8_t {
        None,     ///< normal automatic + manual blinking
        Open,     ///< eyes pinned fully open (blinking suspended)
        Closed    ///< eyes pinned fully closed, e.g. sleep (blinking suspended)
    };

    BlinkSystem() = default;

    // ---- lifecycle ----------------------------------------------------------

    /// Initialise: seed the PRNG, open the eyes, and schedule the first blink.
    /// A fixed default seed keeps behaviour reproducible; pass a varying seed
    /// (e.g. from a hardware timer) for run-to-run variety.
    void begin(uint32_t seed = 0xA5A5A5A5u);

    /// Advance the state machine by `dtMs` milliseconds. Non-blocking; call once
    /// per frame. Safe with dt == 0 and with large dt (dropped frames).
    void update(float dtMs);

    /// Return to the fully-open, idle state and reschedule the next auto-blink.
    void reset();

    // ---- requests -----------------------------------------------------------

    /// Blink once, now — interrupts the idle wait. Ignored while held.
    void requestBlink();

    /// Blink twice in quick succession. Ignored while held.
    void requestDoubleBlink();

    // ---- configuration ------------------------------------------------------

    /// Enable/disable automatic (random) blinking. Manual requests still work
    /// while enabled == true; when disabled the eyes simply stop auto-blinking.
    void setEnabled(bool enabled) { _enabled = enabled; }

    /// Scale blink frequency: 1.0 = normal, >1 = blink more often (shorter
    /// gaps), <1 = less often. Clamped to a sane range. Applies to the next
    /// scheduled wait.
    void setBlinkRate(float rate);

    /// Set the full blink duration (close + brief hold + open), in ms. Takes
    /// effect on the next blink; an in-progress blink finishes at its duration.
    void setBlinkDuration(uint32_t durationMs);

    /// Force the eyes open or closed, or release back to normal blinking.
    void setHold(Hold hold);

    // ---- outputs ------------------------------------------------------------

    /// Normalised eyelid openness for this frame: 1 = open, 0 = shut.
    float eyeOpenAmount() const { return _open; }

    /// True while a blink is in progress (closing, held shut, or opening).
    bool isBlinking() const { return _phase != BlinkState::Open; }

    bool isEnabled() const { return _enabled; }
    Hold hold() const { return _hold; }

private:
    /// Begin a blink: `extraRepeats` additional blinks after this one (1 for a
    /// double blink), using the currently configured duration.
    void startBlink(int extraRepeats);

    /// Pick a new random idle wait (scaled by the blink rate) and go idle.
    void scheduleNext();

    /// xorshift32 PRNG step — cheap, allocation-free, deterministic per seed.
    uint32_t nextRandom();

    // State machine phase. Reuses the shared BlinkState type (Open == idle /
    // eyes-open, waiting for the next blink). Kept private — not exposed.
    BlinkState _phase = BlinkState::Open;

    float    _open            = 1.0f;   ///< live openness output [0,1]
    uint32_t _elapsedMs       = 0;      ///< time accumulated in current phase
    uint32_t _nextGapMs       = 0;      ///< idle wait until the next auto-blink
    uint32_t _configDurationMs = cfg::blink::fastMs;  ///< configured blink length
    uint32_t _activeDurationMs = cfg::blink::fastMs;  ///< length of current blink
    int      _pendingRepeats  = 0;      ///< remaining extra blinks (double)
    float    _rate            = 1.0f;   ///< frequency scale
    bool     _enabled         = true;   ///< automatic blinking on/off
    Hold     _hold            = Hold::None;
    uint32_t _rng             = 0xA5A5A5A5u;
};

}  // namespace aura
