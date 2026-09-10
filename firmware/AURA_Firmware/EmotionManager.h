// =============================================================================
//  face/EmotionManager.h
// -----------------------------------------------------------------------------
//  Converts an Emotion into facial parameters. That is its entire job.
//
//  EmotionManager is a pure lookup: given an Emotion it returns the eye shape,
//  mouth shape, and behaviour hints (blink-rate and gaze-energy modifiers) that
//  define that emotion's default appearance. It RENDERS NOTHING, ANIMATES
//  NOTHING, does not blink, does not touch serial or hardware. Every value it
//  returns is read-only data.
//
//  Smooth cross-fading between emotions (which the old firmware did here) is a
//  time-based animation concern and now belongs to FaceController — keeping this
//  class a stateless-feeling, O(1) data source.
//
//  Allowed dependencies (and no others): core/Types.h, core/Config.h.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"

namespace aura {

class EmotionManager {
public:
    EmotionManager() = default;

    /// Initialise to the neutral emotion.
    void begin();

    /// Select the current emotion (instant, data-only — no animation here).
    void setEmotion(Emotion emotion);

    /// Return to neutral.
    void reset();

    /// The currently selected emotion.
    Emotion currentEmotion() const { return _current; }

    // ---- read-only appearance for the current emotion -----------------------

    /// Eye appearance (shape, openness, pupil, colours) for the current emotion.
    const EyeParams& getEyeParams() const;

    /// Mouth appearance for the current emotion.
    const MouthParams& getMouthParams() const;

    /// Blink-rate modifier: a multiplier for BlinkSystem::setBlinkRate.
    /// >1 = blink more often (excited), <1 = less often (sleepy).
    float getBlinkModifier() const;

    /// Gaze-energy hint in [0,1] for AnimationManager: how lively the idle
    /// wandering should be (0 = still, e.g. sleep; 1 = very active, e.g. search).
    float getGazeEnergy() const;

    // ---- lookup for an arbitrary emotion (without changing the current one) --
    // Useful for FaceController when cross-fading from one emotion to another.

    const EyeParams&   eyeParamsOf(Emotion e) const;
    const MouthParams& mouthParamsOf(Emotion e) const;
    float              blinkModifierOf(Emotion e) const;
    float              gazeEnergyOf(Emotion e) const;

private:
    Emotion _current = Emotion::Neutral;
};

}  // namespace aura
