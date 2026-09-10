// =============================================================================
//  face/FaceController.cpp
// -----------------------------------------------------------------------------
//  Implementation of the face coordinator. The per-frame flow is deliberately
//  linear and deterministic:
//
//      anim.update -> blink.update -> scene.update -> (emotion cues) ->
//      compose EyeState (emotion + animation + blink) -> render eyes ->
//      render mouth -> present
//
//  Everything the frame needs is already owned; no allocation happens here.
// =============================================================================
#include "FaceController.h"

namespace aura {

namespace {
// How long the celebrate face is held after focus completes before returning to
// neutral (preserves the original ~2.6 s celebration).
constexpr uint32_t kCelebrateHoldMs = 2600;
}  // namespace

// ---- lifecycle --------------------------------------------------------------

bool FaceController::begin() {
    if (!_display.begin()) {
        return false;                  // hard failure — do not proceed
    }
    _emotion.begin();
    _anim.begin();
    _blink.begin();
    _expressionRenderer.begin();
    _musicRenderer.begin();
    _countdownRenderer.begin();
    _scene.begin();                    // starts the boot animation

    applyEmotionHints(_emotion.currentEmotion());
    return true;
}

void FaceController::reset() {
    _emotion.reset();
    _anim.reset();
    _blink.reset();
    _expressionRenderer.reset();
    _musicRenderer.reset();
    _countdownRenderer.stop();
    _musicActive = false;
    _musicVisible = false;
    _fullFrameRefreshPending = false;
    _scene.reset();
    _sceneFinishHandled = false;
    _celebrateHoldMs = 0;
    applyEmotionHints(_emotion.currentEmotion());
}

// ---- per-frame --------------------------------------------------------------

void FaceController::update(float dtMs) {
    if (dtMs < 0.0f) dtMs = 0.0f;

    // A normal update always transfers a complete frame, satisfying any
    // pending scene-exit cleanup requested while the microphone was active.
    _fullFrameRefreshPending = false;

    if (_countdownRenderer.active()) {
        _display.beginFrame();
        _countdownRenderer.render();
        _display.endFrame();
        _display.update();
        return;
    }

    if (_musicActive && _musicVisible) {
        _musicRenderer.update(dtMs);
        _display.beginFrame();
        _musicRenderer.render();
        _display.endFrame();
        _display.update();
        return;
    }

    // 1. Advance procedural motion and blink (no drawing).
    _anim.update(dtMs);
    _blink.update(dtMs);
    _expressionRenderer.update(dtMs);

    // 2. Draw the frame as one batched SPI transaction.
    _display.beginFrame();
    _scene.update(dtMs);                 // draws non-face scenes (boot/book/…)
    handleSceneTransitions(dtMs);        // apply emotion cues (no drawing)
    if (_scene.faceVisible()) {
        renderFace();                    // eyes + mouth
    }
    _display.endFrame();

    // 3. Present.
    _display.update();
}

void FaceController::updateEyesOnly(float dtMs) {
    if (dtMs < 0.0f) dtMs = 0.0f;
    if (_countdownRenderer.active()) return;
    if (_fullFrameRefreshPending) {
        _fullFrameRefreshPending = false;
        update(dtMs);
        return;
    }
    _anim.update(dtMs);
    _blink.update(dtMs);
    _expressionRenderer.update(dtMs);
    if (!_scene.faceVisible()) return;

    _display.beginFrame();
    renderFace();
    // The current AURA artwork keeps both eyes and their upper decorations in
    // this strip. Sending ~35k pixels is far cheaper than a 76.8k-pixel frame.
    _display.updateRegion(24, 32, 272, 132);
}

// ---- rendering --------------------------------------------------------------

void FaceController::renderFace() {
    // All face art is drawn into the off-screen framebuffer, so a complete
    // expression appears in one transfer without flicker.
    _display.clear();

    AnimationState anim = _anim.getCurrentAnimationState();
    anim.blink = _blink.eyeOpenAmount();  // BlinkSystem is unchanged.

    _expressionRenderer.render(_emotion.currentEmotion(), anim);
}

// ---- scene → emotion coordination ------------------------------------------

void FaceController::handleSceneTransitions(float dtMs) {
    // Time-out the celebrate hold back to neutral.
    if (_celebrateHoldMs > 0) {
        const uint32_t dt = static_cast<uint32_t>(dtMs);
        _celebrateHoldMs = (dt >= _celebrateHoldMs) ? 0 : _celebrateHoldMs - dt;
        if (_celebrateHoldMs == 0) {
            setEmotion(Emotion::Neutral);
        }
    }

    // Edge-triggered reaction to a scene completing and returning to the face.
    const bool finished = _scene.isSceneFinished() && _scene.faceVisible();
    if (finished && !_sceneFinishHandled) {
        _sceneFinishHandled = true;
        if (_scene.celebrationRequested()) {
            setEmotion(Emotion::Celebrate);
            _celebrateHoldMs = kCelebrateHoldMs;   // auto-revert after the hold
        } else {
            setEmotion(Emotion::Neutral);          // boot done / book aborted
        }
    } else if (!finished) {
        _sceneFinishHandled = false;
    }
}

void FaceController::applyEmotionHints(Emotion emotion) {
    // Blink cadence: excited blinks more often, sleepy less.
    _blink.setBlinkRate(_emotion.blinkModifierOf(emotion));

    // Gaze liveliness: near-still emotions stop wandering; lively ones speed up.
    const float energy = _emotion.gazeEnergyOf(emotion);
    _anim.enableSaccades(energy > 0.1f);
    _anim.setAnimationSpeed(0.6f + energy);        // ~0.6 .. 1.6
}

// ---- high-level commands ----------------------------------------------------

void FaceController::setEmotion(Emotion emotion) {
    if (_emotion.currentEmotion() != emotion) {
        _fullFrameRefreshPending = true;
    }
    _emotion.setEmotion(emotion);
    _expressionRenderer.setEmotion(emotion);
    applyEmotionHints(emotion);
    if (emotion != Emotion::Celebrate) {
        _celebrateHoldMs = 0;                      // manual change cancels revert
    }
}

void FaceController::lookLeft()   { _anim.lookLeft(); }
void FaceController::lookRight()  { _anim.lookRight(); }
void FaceController::lookUp()     { _anim.lookUp(); }
void FaceController::lookDown()   { _anim.lookDown(); }
void FaceController::lookCenter() { _anim.lookCenter(); }
void FaceController::lookAt(float x, float y) { _anim.setTargetPosition(x, y); }

void FaceController::blink()       { _blink.requestBlink(); }
void FaceController::doubleBlink() { _blink.requestDoubleBlink(); }

void FaceController::sleep() {
    setEmotion(Emotion::Sleep);
    _blink.setHold(BlinkSystem::Hold::Closed);     // eyes shut, blinking paused
}

void FaceController::wake() {
    _blink.setHold(BlinkSystem::Hold::None);
    setEmotion(Emotion::Neutral);
}

// ---- scenes -----------------------------------------------------------------

void FaceController::startBookMode() {
    // The book scene hides and draws over the face; the happy/celebrate cues are
    // applied here (celebrate on completion via handleSceneTransitions).
    _scene.startBookMode();
}

void FaceController::stopBookMode(bool celebrate) {
    _scene.stopBookMode(celebrate);
}

void FaceController::startBootAnimation()     { _scene.startBoot(); }
void FaceController::startShutdownAnimation() { _scene.startShutdown(); }

// ---- display ----------------------------------------------------------------

void FaceController::setBrightness(uint8_t level) {
    _display.setBrightness(level);
}

// ---- music visualizer -------------------------------------------------------

void FaceController::startMusicMode() {
    _musicActive = true;
    _musicVisible = true;
}

void FaceController::stopMusicMode() {
    _musicActive = false;
    _musicVisible = false;
    _musicRenderer.reset();
}

void FaceController::suspendMusicDisplay() {
    if (_musicActive) _musicVisible = false;
}

void FaceController::resumeMusicDisplay() {
    if (_musicActive) _musicVisible = true;
}

void FaceController::setMusicMetadata(const char* title, const char* artist) {
    _musicRenderer.setMetadata(title, artist);
}

void FaceController::setMusicPaused(bool paused) {
    _musicRenderer.setPaused(paused);
}

void FaceController::setMusicLevel(uint8_t level) {
    _musicRenderer.setLevel(level);
}

// ---- timer / alarm / reminder scene ---------------------------------------

void FaceController::startCountdown(uint32_t seconds, const char* kind) {
    _countdownRenderer.start(seconds, kind);
    _fullFrameRefreshPending = true;
}

void FaceController::showCountdownAlert(const char* kind) {
    _countdownRenderer.alert(kind);
    _fullFrameRefreshPending = true;
}

void FaceController::stopCountdown() {
    const bool wasActive = _countdownRenderer.active();
    _countdownRenderer.stop();
    if (wasActive) {
        _fullFrameRefreshPending = true;
    }
}

}  // namespace aura
