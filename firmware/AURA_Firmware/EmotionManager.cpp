// =============================================================================
//  face/EmotionManager.cpp
// -----------------------------------------------------------------------------
//  The centralized emotion table. Each emotion's appearance is defined once, in
//  defFor(), as a variation on a neutral base. defFor() runs at COMPILE TIME to
//  populate a constexpr table; at run time every lookup is a plain O(1) array
//  index — no per-frame switch, no computation.
//
//  All emotion values live here and nowhere else. Geometry, colours and the
//  default mouth width come from Config; only the per-emotion deltas are written
//  in the table, so nothing is hardcoded in scattered places.
// =============================================================================
#include "EmotionManager.h"

namespace aura {

namespace {

// One emotion's complete definition: appearance + behaviour hints.
struct EmotionDef {
    EyeParams   eye;
    MouthParams mouth;
    float       blinkModifier;   ///< multiplier for BlinkSystem::setBlinkRate
    float       gazeEnergy;      ///< 0..1 liveliness hint for AnimationManager
};

// Neutral base: a calm, fully-open cyan eye and a small mouth line, built from
// Config so the whole face rescales if the geometry/palette changes.
constexpr EyeParams kBaseEye = {
    cfg::eye::width,        // width
    cfg::eye::height,       // height
    cfg::eye::radius,       // radius
    1.0f,                   // openness
    cfg::eye::pupilScale,   // pupilScale
    0.0f,                   // slant
    0.0f,                   // bottomArc
    PupilShape::Circle,     // pupil
    EyeShape::Rect,         // shape
    cfg::color::eye,        // eyeColor
    cfg::color::pupil       // pupilColor
};

constexpr MouthParams kBaseMouth = {
    MouthShape::Line,       // shape
    cfg::mouth::defaultWidth,
    0.0f                    // open
};

// Build one emotion's definition as a delta from the neutral base. This switch
// executes only at compile time (see kTable below); it is the single, central
// place every emotion is described.
constexpr EmotionDef defFor(Emotion e) {
    EmotionDef d{ kBaseEye, kBaseMouth, 1.0f, 0.8f };

    switch (e) {
        case Emotion::Neutral:
            break;

        case Emotion::Happy:
            // Curved smiling eyes; BlinkSystem still temporarily closes them.
            d.eye.bottomArc = 0.62f;
            d.eye.openness = 0.72f;
            d.eye.pupil = PupilShape::None;
            d.mouth.shape = MouthShape::Smile;
            d.mouth.width = 96.0f;
            break;

        case Emotion::Excited:
            d.eye.width  = cfg::eye::width  * 1.06f;
            d.eye.height = cfg::eye::height * 1.06f;
            d.eye.pupilScale = 0.40f;
            d.mouth.shape = MouthShape::OpenSmile;
            d.mouth.width = 105.0f;
            d.mouth.open = 0.78f;
            d.blinkModifier = 1.67f;
            d.gazeEnergy = 0.9f;
            break;

        case Emotion::Sad:
            d.eye.slant = -0.5f; d.eye.openness = 0.8f; d.eye.pupilScale = 0.36f;
            d.mouth.shape = MouthShape::Sad; d.mouth.width = 90.0f;
            d.blinkModifier = 0.63f; d.gazeEnergy = 0.3f;
            break;

        case Emotion::Angry:
            d.eye.slant = 0.7f; d.eye.height = cfg::eye::height * 0.9f;
            d.eye.pupilScale = 0.34f;
            d.mouth.shape = MouthShape::Sad; d.mouth.width = 72.0f;
            d.blinkModifier = 1.25f; d.gazeEnergy = 0.5f;
            break;

        case Emotion::Surprised:
            d.eye.width  = cfg::eye::width  * 1.10f;
            d.eye.height = cfg::eye::height * 1.18f;
            d.eye.radius = cfg::eye::radius * 1.50f;
            d.eye.pupilScale = 0.30f;
            d.mouth.shape = MouthShape::Round; d.mouth.width = 60.0f;
            d.mouth.open = 0.55f;
            break;

        case Emotion::Confused:
            d.eye.openness = 0.90f;
            d.eye.slant = -0.16f;
            d.eye.pupilScale = 0.38f;
            d.mouth.shape = MouthShape::Slant;
            d.mouth.width = 54.0f;
            d.gazeEnergy = 0.35f;
            break;

        case Emotion::Curious:
            d.eye.width  = cfg::eye::width  * 1.03f;
            d.eye.height = cfg::eye::height * 1.03f;
            d.eye.pupilScale = 0.42f;
            d.mouth.shape = MouthShape::Round;
            d.mouth.width = 42.0f;
            d.mouth.open = 0.18f;
            d.gazeEnergy = 0.8f;
            break;

        case Emotion::Love:
            d.eye.pupil = PupilShape::Heart; d.eye.pupilColor = cfg::color::love;
            d.eye.pupilScale = 0.62f;
            d.mouth.shape = MouthShape::Smile; d.mouth.width = 100.0f;
            break;

        case Emotion::Thinking:
            d.eye.openness = 0.88f;
            d.eye.pupilScale = 0.36f;
            d.mouth.shape = MouthShape::Sad;
            d.mouth.width = 54.0f;
            d.blinkModifier = 0.83f;
            d.gazeEnergy = 0.15f;
            break;

        case Emotion::Listening:
            d.eye.height = cfg::eye::height * 1.03f; d.eye.pupilScale = 0.44f;
            d.mouth.shape = MouthShape::Smile; d.mouth.width = 52.0f;
            d.blinkModifier = 0.77f; d.gazeEnergy = 0.05f;   // steady eye contact
            break;

        case Emotion::Searching:
            d.eye.width = cfg::eye::width * 1.04f;
            d.mouth.shape = MouthShape::Line; d.mouth.width = 50.0f;
            d.gazeEnergy = 1.0f;
            break;

        case Emotion::Worried:
            d.eye.slant = -0.18f;
            d.eye.openness = 0.88f;
            d.eye.pupilScale = 0.40f;
            d.mouth.shape = MouthShape::Sad;
            d.mouth.width = 72.0f;
            d.blinkModifier = 0.83f;
            d.gazeEnergy = 0.30f;
            break;

        case Emotion::Celebrate:
            d.eye.shape = EyeShape::Star; d.eye.eyeColor = cfg::color::star;
            d.eye.pupil = PupilShape::None;
            d.mouth.shape = MouthShape::OpenSmile; d.mouth.width = 124.0f;
            d.mouth.open = 1.0f;
            d.blinkModifier = 1.67f; d.gazeEnergy = 0.9f;
            break;

        case Emotion::Sleepy:
            d.eye.openness = 0.20f;
            d.eye.pupil = PupilShape::None;
            d.eye.bottomArc = 0.22f;
            d.mouth.shape = MouthShape::Line;
            d.mouth.width = 38.0f;
            d.blinkModifier = 0.40f;
            d.gazeEnergy = 0.0f;
            break;

        case Emotion::Sleep:
            d.eye.openness = 0.06f; d.eye.pupil = PupilShape::None;
            d.mouth.shape = MouthShape::None;
            d.blinkModifier = 0.17f; d.gazeEnergy = 0.0f;
            break;

        case Emotion::Error:
            d.eye.eyeColor = cfg::color::error; d.eye.openness = 0.55f;
            d.eye.pupil = PupilShape::None; d.eye.height = cfg::eye::height * 0.7f;
            d.mouth.shape = MouthShape::Wavy; d.mouth.width = 70.0f;
            break;
    }
    return d;
}

// The compile-time table, in Emotion-enum order. Every entry is produced by the
// constexpr defFor() above, so appearance is defined once and looked up as a
// plain array index at run time.
constexpr EmotionDef kTable[] = {
    defFor(Emotion::Neutral),   defFor(Emotion::Happy),
    defFor(Emotion::Excited),   defFor(Emotion::Sad),
    defFor(Emotion::Angry),     defFor(Emotion::Surprised),
    defFor(Emotion::Confused),  defFor(Emotion::Curious),
    defFor(Emotion::Love),      defFor(Emotion::Thinking),
    defFor(Emotion::Listening), defFor(Emotion::Searching),
    defFor(Emotion::Worried),   defFor(Emotion::Celebrate),
    defFor(Emotion::Sleepy),    defFor(Emotion::Sleep),
    defFor(Emotion::Error),
};

constexpr int kEmotionCount = sizeof(kTable) / sizeof(kTable[0]);
static_assert(kEmotionCount == 17,
              "kTable must contain exactly one entry per Emotion");
static_assert(static_cast<int>(Emotion::Error) == kEmotionCount - 1,
              "kTable order must match the Emotion enum");

// Bounds-checked index into the table.
inline const EmotionDef& lookup(Emotion e) {
    const int i = static_cast<int>(e);
    if (i < 0 || i >= kEmotionCount) {
        return kTable[static_cast<int>(Emotion::Neutral)];
    }
    return kTable[i];
}

}  // namespace

// ---- public API -------------------------------------------------------------

void EmotionManager::begin() { _current = Emotion::Neutral; }
void EmotionManager::reset() { _current = Emotion::Neutral; }
void EmotionManager::setEmotion(Emotion emotion) { _current = emotion; }

const EyeParams&   EmotionManager::getEyeParams()   const { return lookup(_current).eye; }
const MouthParams& EmotionManager::getMouthParams() const { return lookup(_current).mouth; }
float EmotionManager::getBlinkModifier() const { return lookup(_current).blinkModifier; }
float EmotionManager::getGazeEnergy()    const { return lookup(_current).gazeEnergy; }

const EyeParams&   EmotionManager::eyeParamsOf(Emotion e)   const { return lookup(e).eye; }
const MouthParams& EmotionManager::mouthParamsOf(Emotion e) const { return lookup(e).mouth; }
float EmotionManager::blinkModifierOf(Emotion e) const { return lookup(e).blinkModifier; }
float EmotionManager::gazeEnergyOf(Emotion e)    const { return lookup(e).gazeEnergy; }

}  // namespace aura
