// =============================================================================
//  face/BlinkSystem.cpp
// -----------------------------------------------------------------------------
//  Implementation of the blink timing state machine.
//
//  A blink runs: Closing -> Closed (brief hold) -> Opening -> back to Open
//  (idle). Openness is eased with a smooth in/out-quadratic curve for a natural
//  lid motion. All timing is driven by the delta time passed to update(); there
//  is no delay() and no blocking anywhere.
// =============================================================================
#include "BlinkSystem.h"

namespace aura {

namespace {
// Header-free numeric helpers (internal linkage — not globals).
inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// Smooth in/out quadratic easing on t in [0,1]. Pure arithmetic (no math lib).
inline float inOutQuad(float t) {
    if (t < 0.5f) {
        return 2.0f * t * t;
    }
    const float f = -2.0f * t + 2.0f;
    return 1.0f - (f * f) * 0.5f;
}

// Proportions of a full blink spent closing / held shut / opening (sum == 1).
constexpr float kCloseFraction  = 0.44f;
constexpr float kClosedFraction = 0.12f;
constexpr float kOpenFraction   = 0.44f;

// Clamp range for the frequency scale and a floor for the blink duration.
constexpr float    kMinRate        = 0.1f;
constexpr float    kMaxRate        = 10.0f;
constexpr uint32_t kMinDurationMs  = 40;
}  // namespace

// ---- lifecycle --------------------------------------------------------------

void BlinkSystem::begin(uint32_t seed) {
    _rng = (seed != 0u) ? seed : 0xA5A5A5A5u;   // xorshift must not be seeded 0
    reset();
}

void BlinkSystem::reset() {
    _open           = 1.0f;
    _phase          = BlinkState::Open;
    _pendingRepeats = 0;
    _hold           = Hold::None;
    scheduleNext();
}

// ---- requests ---------------------------------------------------------------

void BlinkSystem::requestBlink() {
    if (_hold != Hold::None) {
        return;
    }
    startBlink(0);
}

void BlinkSystem::requestDoubleBlink() {
    if (_hold != Hold::None) {
        return;
    }
    startBlink(1);
}

// ---- configuration ----------------------------------------------------------

void BlinkSystem::setBlinkRate(float rate) {
    _rate = clampf(rate, kMinRate, kMaxRate);
}

void BlinkSystem::setBlinkDuration(uint32_t durationMs) {
    _configDurationMs = (durationMs < kMinDurationMs) ? kMinDurationMs : durationMs;
}

void BlinkSystem::setHold(Hold hold) {
    _hold = hold;
    if (hold == Hold::Open) {
        _open  = 1.0f;
        _phase = BlinkState::Open;
    } else if (hold == Hold::Closed) {
        _open  = 0.0f;
        _phase = BlinkState::Open;    // idle phase; openness pinned by the hold
    } else {
        // Released: resume from open and schedule a fresh wait.
        _open = 1.0f;
        scheduleNext();
    }
}

// ---- update -----------------------------------------------------------------

void BlinkSystem::update(float dtMs) {
    if (dtMs < 0.0f) {
        dtMs = 0.0f;
    }

    // A hold overrides the schedule entirely.
    if (_hold == Hold::Open) {
        _open = 1.0f;
        return;
    }
    if (_hold == Hold::Closed) {
        _open = 0.0f;
        return;
    }

    _elapsedMs += static_cast<uint32_t>(dtMs);

    switch (_phase) {
        case BlinkState::Open:   // idle: waiting for the next automatic blink
            if (_enabled && _elapsedMs >= _nextGapMs) {
                startBlink(0);
            }
            break;

        case BlinkState::Closing: {
            const float dur = _activeDurationMs * kCloseFraction;
            const float t   = clampf(_elapsedMs / (dur > 0.0f ? dur : 1.0f),
                                     0.0f, 1.0f);
            _open = 1.0f - inOutQuad(t);
            if (t >= 1.0f) {
                _phase     = BlinkState::Closed;
                _elapsedMs = 0;
            }
            break;
        }

        case BlinkState::Closed: {
            _open = 0.0f;
            const float dur = _activeDurationMs * kClosedFraction;
            if (_elapsedMs >= static_cast<uint32_t>(dur)) {
                _phase     = BlinkState::Opening;
                _elapsedMs = 0;
            }
            break;
        }

        case BlinkState::Opening: {
            const float dur = _activeDurationMs * kOpenFraction;
            const float t   = clampf(_elapsedMs / (dur > 0.0f ? dur : 1.0f),
                                     0.0f, 1.0f);
            _open = inOutQuad(t);
            if (t >= 1.0f) {
                _open = 1.0f;
                if (_pendingRepeats > 0) {      // double blink: go again
                    --_pendingRepeats;
                    _phase     = BlinkState::Closing;
                    _elapsedMs = 0;
                } else {
                    scheduleNext();             // back to idle waiting
                }
            }
            break;
        }
    }
}

// ---- private ----------------------------------------------------------------

void BlinkSystem::startBlink(int extraRepeats) {
    _activeDurationMs = _configDurationMs;
    _pendingRepeats   = extraRepeats;
    _phase            = BlinkState::Closing;
    _elapsedMs        = 0;
}

void BlinkSystem::scheduleNext() {
    const uint32_t span = cfg::blink::maxGap - cfg::blink::minGap;
    const uint32_t base = cfg::blink::minGap + (span > 0 ? nextRandom() % span : 0);
    // Higher rate -> shorter gap. _rate is always >= kMinRate.
    _nextGapMs = static_cast<uint32_t>(base / _rate);
    _elapsedMs = 0;
    _phase     = BlinkState::Open;
}

uint32_t BlinkSystem::nextRandom() {
    // xorshift32: fast, allocation-free, good enough for blink jitter.
    _rng ^= _rng << 13;
    _rng ^= _rng >> 17;
    _rng ^= _rng << 5;
    return _rng;
}

}  // namespace aura
