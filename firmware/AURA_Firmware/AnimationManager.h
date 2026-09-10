// =============================================================================
//  face/AnimationManager.h
// -----------------------------------------------------------------------------
//  Procedural face animation — the maths of motion, and nothing else.
//
//  AnimationManager computes how the eyes drift, dart, and breathe over time:
//  smooth gaze interpolation, random saccades, micro-tremor, and a breathing
//  bob. It DECIDES NO EMOTIONS, RENDERS NOTHING, and TOUCHES NO HARDWARE. It
//  only produces animation values that a renderer can later consume.
//
//  Its primary output is an AnimationState (gaze + bob) — exactly the type
//  EyeRenderer reads. The blink field is left at 1.0: blinking is owned by
//  BlinkSystem, and FaceController overwrites that field before rendering.
//
//  Allowed dependencies (and no others): core/Types.h, core/Config.h.
//  Deliberately excludes <Arduino.h>, <cmath>, and Easing.h: randomness comes
//  from a built-in PRNG, the breathing sine from a local approximation, and
//  interpolation from a small internal tween — so the class is fully
//  deterministic and unit-testable on any host.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"

namespace aura {

class AnimationManager {
public:
    /// Easing curve applied to gaze transitions.
    enum class Easing : uint8_t { Linear, EaseInOut, EaseOut };

    AnimationManager() = default;

    // ---- lifecycle ----------------------------------------------------------

    /// Initialise: seed the PRNG, centre the gaze, and schedule the first
    /// saccade. A fixed default seed keeps motion reproducible.
    void begin(uint32_t seed = 0x1D2E3F40u);

    /// Advance all animation by `dtMs` milliseconds. Non-blocking; call once per
    /// frame. Safe with dt == 0 and large dt.
    void update(float dtMs);

    /// Recentre gaze, stop transitions, and reschedule idle motion.
    void reset();

    // ---- gaze targets -------------------------------------------------------

    /// Set a normalised gaze target (x, y in [-1, 1]); the eyes interpolate
    /// toward it. Suppresses random saccades briefly so the target "sticks".
    /// (Face-tracking on the laptop feeds in through here.)
    void setTargetPosition(float x, float y);

    void lookLeft();
    void lookRight();
    void lookUp();
    void lookDown();
    void lookCenter();

    // ---- toggles ------------------------------------------------------------

    void enableIdleMotion(bool on) { _idleMotion = on; }   ///< micro-tremor
    void enableBreathing(bool on)  { _breathing = on; }    ///< vertical bob
    void enableSaccades(bool on)   { _saccades = on; }     ///< random darts

    /// Scale animation speed: 1.0 = normal, >1 = snappier transitions & more
    /// frequent saccades. Clamped to a sane range. Breathing keeps its natural
    /// period regardless (it is physiological, not a UI speed).
    void setAnimationSpeed(float speed);

    /// Choose the easing curve used for gaze transitions.
    void setEasing(Easing easing) { _easing = easing; }

    // ---- outputs ------------------------------------------------------------

    /// The packed animation for this frame: gazeX/gazeY (normalised pupil
    /// offset) and bob (vertical breathing, px). blink is left at 1.0 for
    /// FaceController to fill from BlinkSystem. This is what the renderer reads.
    AnimationState getCurrentAnimationState() const;

    // Individual values, also useful for tests and future consumers. In this
    // face design the pupil is what moves horizontally (gaze); the eye's
    // vertical offset is the breathing bob — there is no separate horizontal
    // whole-eye translation in the current render pipeline.
    float pupilOffsetX() const;         ///< normalised gaze X incl. micro-tremor
    float pupilOffsetY() const;         ///< normalised gaze Y incl. micro-tremor
    float breathingOffset() const { return _breathing ? _bob : 0.0f; }  ///< px
    float animationProgress() const;    ///< 0..1 progress of the current dart

private:
    // Small internal tween: interpolates one value from `from` to `to` over a
    // duration with an easing curve. Header-declared (needed for member
    // storage); methods are defined in the .cpp.
    struct Tween {
        float   from = 0.0f, to = 0.0f, cur = 0.0f;
        float   elapsed = 0.0f, duration = 1.0f;
        bool    active = false;
        Easing  easing = Easing::EaseOut;

        void  set(float v);                                   // jump, no anim
        void  retarget(float target, float ms, Easing e);     // animate to target
        void  update(float dtMs);
        float value() const { return cur; }
        float progress() const;
    };

    void scheduleSaccade();
    uint32_t nextRandom();
    float randUnit();                    ///< uniform random in [-1, 1]

    Tween _gazeX;                        ///< normalised gaze target X
    Tween _gazeY;                        ///< normalised gaze target Y

    float    _bob         = 0.0f;        ///< breathing bob (px)
    uint32_t _breathMs    = 0;           ///< breathing phase accumulator
    float    _jitterX     = 0.0f;        ///< micro-tremor offset (normalised)
    float    _jitterY     = 0.0f;
    uint32_t _jitterMs    = 0;           ///< time since last tremor refresh
    uint32_t _saccadeMs   = 0;           ///< time since last saccade
    uint32_t _saccadeGap  = 0;           ///< wait until next saccade
    uint32_t _holdMs      = 0;           ///< suppress saccades while > 0

    bool  _idleMotion = true;
    bool  _breathing  = true;
    bool  _saccades   = true;
    float _speed      = 1.0f;
    Easing _easing    = Easing::EaseOut;

    uint32_t _rng = 0x1D2E3F40u;
};

}  // namespace aura
