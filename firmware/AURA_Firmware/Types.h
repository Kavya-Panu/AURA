// =============================================================================
//  core/Types.h
// -----------------------------------------------------------------------------
//  Shared data types for the AURA face firmware.
//
//  This header contains ONLY data: enums and plain-old-data (POD) structs that
//  more than one module needs to agree on. There are deliberately:
//     * no functions        (types describe data, they do not act on it)
//     * no rendering code    (that lives in face/EyeRenderer, MouthRenderer)
//     * no hardware code     (that lives in display/ and hardware/)
//     * no configuration values (those live in core/Config.h)
//
//  Because it is pure data with no dependencies of its own, every module may
//  include this file freely without creating a dependency cycle.
// =============================================================================
#pragma once

#include <cstdint>

namespace aura {

// -----------------------------------------------------------------------------
//  Enumerations
//  All are `enum class` (scoped, no implicit int conversion) with an explicit
//  uint8_t underlying type to keep the structs below tightly packed.
// -----------------------------------------------------------------------------

/// Which of the two eyes a value refers to.
enum class Eye : uint8_t { Left, Right };

/// Overall silhouette of an eye. RECT is the normal rounded-rectangle eye;
/// STAR is the gold star-eye used for the celebrate expression.
enum class EyeShape : uint8_t { Rect, Star };

/// Shape drawn for the pupil / inner eye.
enum class PupilShape : uint8_t { Circle, Heart, None };

/// Shape of the mouth for a given expression. Rendered by MouthRenderer.
enum class MouthShape : uint8_t {
    None,        ///< no mouth drawn
    Line,        ///< flat neutral line
    Smile,       ///< upward curve
    Sad,         ///< downward curve
    OpenSmile,   ///< open happy mouth (uses `open`)
    Round,       ///< "O" shape (uses `open`)
    Wavy,        ///< worried / unsure
    Slant        ///< angled (angry / smug)
};

/// The high-level emotions the laptop can request. These map 1:1 onto the
/// tokens the brain sends over serial; EmotionManager converts each into
/// concrete EyeParams + MouthParams. Kept in sync with the laptop-side set.
enum class Emotion : uint8_t {
    Neutral,
    Happy,
    Excited,
    Sad,
    Angry,
    Surprised,
    Confused,
    Curious,
    Love,
    Thinking,
    Listening,
    Searching,
    Worried,
    Celebrate,
    Sleepy,
    Sleep,
    Error
};

/// Discrete gaze directions the laptop can command (LOOK LEFT / RIGHT / ...).
/// Continuous gaze is still expressed as floats in EyeState; this enum is the
/// command-level intent that AnimationManager turns into a target offset.
enum class EyeDirection : uint8_t { Center, Left, Right, Up, Down };

/// Where the blink system currently is in a blink cycle.
enum class BlinkState : uint8_t { Open, Closing, Closed, Opening };

/// Landscape orientation options passed to the display. Values match the
/// TFT_eSPI rotation index so DisplayManager can forward them directly.
enum class DisplayRotation : uint8_t {
    Portrait = 0,
    Landscape = 1,
    PortraitFlipped = 2,
    LandscapeFlipped = 3
};

// -----------------------------------------------------------------------------
//  Data structures (plain data — no methods)
// -----------------------------------------------------------------------------

/// Static per-emotion shape of a single eye. AnimationManager tweens between
/// these presets; EyeRenderer draws from the resolved result. Field defaults
/// describe the neutral eye and are filled in from Config at construction by
/// the modules that build these (this struct itself stays value-initialised).
struct EyeParams {
    float      width      = 0.0f;   ///< eye width in px
    float      height     = 0.0f;   ///< eye height in px
    float      radius     = 0.0f;   ///< corner radius in px
    float      openness   = 1.0f;   ///< 0 = shut, 1 = fully open
    float      pupilScale = 0.0f;   ///< pupil size as a fraction of the eye
    float      slant      = 0.0f;   ///< + = angry tilt, - = sad tilt
    float      bottomArc  = 0.0f;   ///< carves a happy crescent when > 0
    PupilShape pupil      = PupilShape::Circle;
    EyeShape   shape      = EyeShape::Rect;
    uint16_t   eyeColor   = 0;      ///< RGB565; set from Config by builder
    uint16_t   pupilColor = 0;      ///< RGB565
};

/// Static per-emotion shape of the mouth.
struct MouthParams {
    MouthShape shape = MouthShape::Line;
    float      width = 0.0f;   ///< mouth width in px
    float      open  = 0.0f;   ///< 0..1 opening amount (OpenSmile / Round / talk)
};

/// The animated part of an eye for the current frame: where it is looking, how
/// far through a blink it is, and any vertical bob. Combined with EyeParams to
/// produce a fully-resolved EyeState.
struct AnimationState {
    float gazeX = 0.0f;   ///< -1..1 horizontal gaze offset
    float gazeY = 0.0f;   ///< -1..1 vertical gaze offset
    float blink = 1.0f;   ///< 1 = open, 0 = fully closed (lid position)
    float bob   = 0.0f;   ///< vertical breathing offset in px
};

/// A fully-resolved eye for one frame: its static shape plus this frame's
/// animation. This is the exact input EyeRenderer consumes. It is intentionally
/// a plain data carrier with NO behaviour — logic that fills it lives in
/// FaceController / AnimationManager, drawing that reads it lives in EyeRenderer.
struct EyeState {
    EyeParams      params;                 ///< static shape for the emotion
    AnimationState anim;                   ///< this frame's motion
    Eye            eye = Eye::Left;         ///< which eye this describes
};

}  // namespace aura
