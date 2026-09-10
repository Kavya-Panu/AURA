// =============================================================================
//  face/AnimationManager.cpp
// -----------------------------------------------------------------------------
//  Implementation of the procedural animation maths. All motion is driven by
//  the delta time passed to update(); there is no delay() and no blocking. The
//  algorithms (random saccades biased to centre, micro-tremor, a sine breathing
//  bob, eased gaze interpolation) are ported from the original firmware.
// =============================================================================
#include "AnimationManager.h"

namespace aura {

namespace {
// ---- header-free numeric helpers (internal linkage — not globals) ----------

inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
inline float lerpf(float a, float b, float t) { return a + (b - a) * t; }
inline float absf(float v) { return v < 0.0f ? -v : v; }

// Easing curves on t in [0,1].
inline float easeLinear(float t) { return t; }
inline float easeInOut(float t) {                        // in/out quadratic
    if (t < 0.5f) return 2.0f * t * t;
    const float f = -2.0f * t + 2.0f;
    return 1.0f - (f * f) * 0.5f;
}
inline float easeOut(float t) {                          // out cubic
    const float f = 1.0f - t;
    return 1.0f - f * f * f;
}
inline float applyEase(AnimationManager::Easing e, float t) {
    switch (e) {
        case AnimationManager::Easing::Linear:    return easeLinear(t);
        case AnimationManager::Easing::EaseInOut: return easeInOut(t);
        default:                                  return easeOut(t);
    }
}

// Parabolic sine approximation (max err ~0.2%). Pure arithmetic, no math lib.
// Good enough for a gentle breathing bob and keeps the class include-free.
inline float fastSin(float x) {
    constexpr float kPi    = 3.14159265358979f;
    constexpr float kTwoPi = 6.28318530717959f;
    while (x >  kPi) x -= kTwoPi;
    while (x < -kPi) x += kTwoPi;
    constexpr float B = 4.0f / kPi;
    constexpr float C = -4.0f / (kPi * kPi);
    float y = B * x + C * x * absf(x);
    constexpr float P = 0.225f;                          // refinement term
    y = P * (y * absf(y) - y) + y;
    return y;
}

// Animation tuning that isn't board geometry (kept out of magic numbers).
constexpr float    kMinSpeed          = 0.1f;
constexpr float    kMaxSpeed          = 5.0f;
constexpr float    kTargetTransitMs   = 180.0f;   // gaze move to an explicit target
constexpr uint32_t kExternalHoldMs    = 900;      // suppress saccades after a target
constexpr uint32_t kJitterPeriodMs    = 180;      // micro-tremor refresh interval
constexpr float    kMicroJitterNorm   = 0.11f;    // ~cfg micro-jitter / pupil range
constexpr float    kSaccadeCentreBias = 0.34f;    // chance a saccade just recentres
}  // namespace

// =============================================================================
//  Tween
// =============================================================================
void AnimationManager::Tween::set(float v) {
    from = to = cur = v;
    elapsed = 0.0f;
    active = false;
}

void AnimationManager::Tween::retarget(float target, float ms, Easing e) {
    from     = cur;
    to       = target;
    duration = ms > 1.0f ? ms : 1.0f;
    elapsed  = 0.0f;
    easing   = e;
    active   = true;
}

void AnimationManager::Tween::update(float dtMs) {
    if (!active) return;
    elapsed += dtMs;
    float t = elapsed / duration;
    if (t >= 1.0f) { t = 1.0f; active = false; }
    cur = lerpf(from, to, applyEase(easing, t));
}

float AnimationManager::Tween::progress() const {
    if (!active) return 1.0f;
    const float t = elapsed / duration;
    return clampf(t, 0.0f, 1.0f);
}

// =============================================================================
//  AnimationManager
// =============================================================================
void AnimationManager::begin(uint32_t seed) {
    _rng = (seed != 0u) ? seed : 0x1D2E3F40u;
    reset();
}

void AnimationManager::reset() {
    _gazeX.set(0.0f);
    _gazeY.set(0.0f);
    _bob = 0.0f;
    _breathMs = 0;
    _jitterX = _jitterY = 0.0f;
    _jitterMs = 0;
    _saccadeMs = 0;
    _holdMs = 0;
    scheduleSaccade();
}

// ---- gaze targets -----------------------------------------------------------

void AnimationManager::setTargetPosition(float x, float y) {
    x = clampf(x, -1.0f, 1.0f);
    y = clampf(y, -1.0f, 1.0f);
    _gazeX.retarget(x, kTargetTransitMs, _easing);
    _gazeY.retarget(y, kTargetTransitMs, _easing);
    _holdMs = kExternalHoldMs;          // keep the target; skip saccades a while
}

void AnimationManager::lookLeft()   { setTargetPosition(-0.8f, 0.0f); }
void AnimationManager::lookRight()  { setTargetPosition( 0.8f, 0.0f); }
void AnimationManager::lookUp()     { setTargetPosition( 0.0f, -0.7f); }
void AnimationManager::lookDown()   { setTargetPosition( 0.0f, 0.7f); }
void AnimationManager::lookCenter() { setTargetPosition( 0.0f, 0.0f); }

// ---- configuration ----------------------------------------------------------

void AnimationManager::setAnimationSpeed(float speed) {
    _speed = clampf(speed, kMinSpeed, kMaxSpeed);
}

// ---- update -----------------------------------------------------------------

void AnimationManager::update(float dtMs) {
    if (dtMs < 0.0f) dtMs = 0.0f;
    const uint32_t dt = static_cast<uint32_t>(dtMs);

    // Gaze transitions run on scaled time so animation speed feels snappier.
    const float gazeDt = dtMs * _speed;
    _gazeX.update(gazeDt);
    _gazeY.update(gazeDt);

    // --- Breathing bob: smooth sine over the configured period (natural rate).
    if (_breathing) {
        _breathMs = (_breathMs + dt) % cfg::idle::breathPeriodMs;
        const float phase = (static_cast<float>(_breathMs) /
                             cfg::idle::breathPeriodMs) * 6.28318530717959f;
        _bob = fastSin(phase) * cfg::idle::breathAmplitude;
    } else {
        _bob = 0.0f;
    }

    // --- Micro-tremor: refresh a tiny random offset a few times a second.
    if (_idleMotion) {
        _jitterMs += dt;
        if (_jitterMs >= kJitterPeriodMs) {
            _jitterMs = 0;
            _jitterX = randUnit() * kMicroJitterNorm;
            _jitterY = randUnit() * kMicroJitterNorm;
        }
    } else {
        _jitterX = _jitterY = 0.0f;
    }

    // --- Random idle saccades (unless a target is being held or disabled).
    if (_holdMs > dt) {
        _holdMs -= dt;
    } else {
        _holdMs = 0;
        if (_saccades) {
            _saccadeMs += dt;
            if (_saccadeMs >= _saccadeGap) {
                scheduleSaccade();
            }
        }
    }
}

// ---- outputs ----------------------------------------------------------------

float AnimationManager::pupilOffsetX() const {
    return clampf(_gazeX.value() + _jitterX, -1.0f, 1.0f);
}
float AnimationManager::pupilOffsetY() const {
    return clampf(_gazeY.value() + _jitterY, -1.0f, 1.0f);
}
float AnimationManager::animationProgress() const {
    // Progress of the slower of the two gaze axes (the one still moving).
    const float px = _gazeX.progress();
    const float py = _gazeY.progress();
    return px < py ? px : py;
}

AnimationState AnimationManager::getCurrentAnimationState() const {
    AnimationState s;
    s.gazeX = pupilOffsetX();
    s.gazeY = pupilOffsetY();
    s.bob   = breathingOffset();
    s.blink = 1.0f;              // owned by BlinkSystem; FaceController fills it
    return s;
}

// ---- private ----------------------------------------------------------------

void AnimationManager::scheduleSaccade() {
    // 1-in-3-ish chance to just recentre, so the eyes keep returning "to you".
    float tx, ty;
    if (randUnit() < (kSaccadeCentreBias * 2.0f - 1.0f)) {
        tx = 0.0f;
        ty = 0.0f;
    } else {
        tx = randUnit() * 0.9f;
        ty = randUnit() * 0.6f;     // less vertical wander than horizontal
    }
    _gazeX.retarget(tx, cfg::idle::saccadeMs, Easing::EaseOut);
    _gazeY.retarget(ty, cfg::idle::saccadeMs, Easing::EaseOut);

    const uint32_t span = cfg::idle::saccadeMaxGap - cfg::idle::saccadeMinGap;
    const uint32_t base = cfg::idle::saccadeMinGap +
                          (span > 0 ? nextRandom() % span : 0);
    // Higher speed -> more frequent saccades.
    _saccadeGap = static_cast<uint32_t>(base / _speed);
    _saccadeMs  = 0;
}

uint32_t AnimationManager::nextRandom() {
    _rng ^= _rng << 13;
    _rng ^= _rng >> 17;
    _rng ^= _rng << 5;
    return _rng;
}

float AnimationManager::randUnit() {
    // Uniform in [-1, 1] from the top bits of the PRNG.
    return (static_cast<float>(nextRandom() % 2001) - 1000.0f) / 1000.0f;
}

}  // namespace aura
