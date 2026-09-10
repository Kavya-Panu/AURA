// =============================================================================
//  face/FaceController.h
// -----------------------------------------------------------------------------
//  The central coordinator of the face engine, and the ONLY public interface for
//  controlling the robot's face.
//
//  FaceController owns the display and the six face modules (emotion, animation,
//  blink, the two renderers, and scenes), drives them in a fixed per-frame
//  order, and merges their outputs into the final picture. No other module talks
//  to those managers directly — they are all private here.
//
//  It coordinates; it does not decide. It never touches serial, sensors, AI, or
//  behaviour. High-level commands come in (setEmotion, lookLeft, startBookMode…)
//  and it translates them into the right calls on the modules it owns.
//
//  Allowed dependencies: the face modules + Types/Config. It must NOT include
//  SerialManager, CommandParser, or any hardware sensor manager.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"
#include "DisplayManager.h"
#include "EmotionManager.h"
#include "AnimationManager.h"
#include "BlinkSystem.h"
#include "SceneManager.h"
#include "ExpressionRenderer.h"
#include "MusicRenderer.h"
#include "CountdownRenderer.h"

namespace aura {

class FaceController {
public:
    FaceController() = default;

    FaceController(const FaceController&)            = delete;
    FaceController& operator=(const FaceController&) = delete;

    // ---- lifecycle ----------------------------------------------------------

    /// Initialise the display and every face module. Returns false if the
    /// display failed to initialise (the only hard failure point); the caller
    /// must not proceed to update() in that case.
    bool begin();

    /// Advance and render one frame. Non-blocking; call once per loop with the
    /// elapsed milliseconds since the previous call.
    void update(float dtMs);

    /// Advance the face and present only the eye area. This keeps tracking and
    /// blinking visible without starving the 50 fps microphone stream.
    void updateEyesOnly(float dtMs);

    /// Return the whole face subsystem to its default idle state.
    void reset();

    // ---- high-level face commands ------------------------------------------

    void setEmotion(Emotion emotion);

    void lookLeft();
    void lookRight();
    void lookUp();
    void lookDown();
    void lookCenter();
    /// Smooth normalized gaze target used by laptop face tracking.
    void lookAt(float x, float y);

    void blink();
    void doubleBlink();

    void sleep();   ///< eyes closed, blinking suspended
    void wake();    ///< back to a neutral, awake face

    // ---- scenes -------------------------------------------------------------

    void startBookMode();
    void stopBookMode(bool celebrate = true);
    void startBootAnimation();
    void startShutdownAnimation();

    // ---- display ------------------------------------------------------------

    void setBrightness(uint8_t level);

    // ---- music visualizer ---------------------------------------------------
    void startMusicMode();
    void stopMusicMode();
    void suspendMusicDisplay();
    void resumeMusicDisplay();
    bool musicModeActive() const { return _musicActive; }
    void setMusicMetadata(const char* title, const char* artist);
    void setMusicPaused(bool paused);
    void setMusicLevel(uint8_t level);

    // ---- timer / alarm / reminder scene -----------------------------------
    void startCountdown(uint32_t seconds, const char* kind = "TIMER");
    void showCountdownAlert(const char* kind = "TIMER");
    void stopCountdown();
    bool countdownActive() const { return _countdownRenderer.active(); }
    bool fullFrameRefreshPending() const { return _fullFrameRefreshPending; }

    // ---- read-only observation (high-level only) ----------------------------

    Emotion              currentEmotion() const { return _emotion.currentEmotion(); }
    SceneManager::Scene  currentScene()   const { return _scene.currentScene(); }

private:
    /// Merge emotion params + animation offsets + blink into an EyeState and
    /// draw eyes then mouth. Called only when the face scene is visible.
    void renderFace();

    /// React to scene completion (book done → celebrate, boot done → show face)
    /// by applying the appropriate emotion cue. Edge-triggered.
    void handleSceneTransitions(float dtMs);

    /// Push an emotion's behaviour hints (blink rate, gaze energy) to the
    /// animation and blink modules.
    void applyEmotionHints(Emotion emotion);

    // Ownership. _display is declared FIRST so the renderers and scene can bind
    // their DisplayManager& to it during construction.
    DisplayManager   _display;
    EmotionManager   _emotion;
    AnimationManager _anim;
    BlinkSystem      _blink;
    SceneManager     _scene{_display};
    ExpressionRenderer _expressionRenderer{_display};
    MusicRenderer      _musicRenderer{_display};
    CountdownRenderer  _countdownRenderer{_display};
    bool _musicActive = false;
    bool _musicVisible = false;
    // Microphone streaming normally refreshes only the eye strip.  Scene exits
    // such as TIMER STOP need one complete transfer so text below the eyes is
    // erased instead of remaining visible over the wake face.
    bool _fullFrameRefreshPending = false;
    // Scene→emotion coordination state.
    bool     _sceneFinishHandled = false;
    uint32_t _celebrateHoldMs    = 0;   ///< >0 while holding the celebrate face
};

}  // namespace aura
