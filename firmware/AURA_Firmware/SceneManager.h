// =============================================================================
//  face/SceneManager.h
// -----------------------------------------------------------------------------
//  Coordinates high-level visual scenes: boot animation, the idle face scene,
//  book (focus) mode, and shutdown. It owns each scene's timing and draws the
//  NON-FACE scenes (the AURA boot logo, the animated book, the shutdown effect)
//  through DisplayManager.
//
//  It does NOT decide emotions, animate or render eyes, blink, talk to serial,
//  or control hardware directly. The face itself (the "Idle" scene) is drawn by
//  FaceController when this manager reports faceVisible(); the emotion cues that
//  used to live here (happy on focus entry, celebrate on completion) are now
//  FaceController's job, driven by polling currentScene()/isSceneFinished()/
//  celebrationRequested(). That is why this class needs no EmotionManager,
//  AnimationManager, or renderer references — it only draws scenes and reports
//  state.
//
//  Allowed dependencies (and no others): core/Types.h, core/Config.h,
//  display/DisplayManager.h.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"
#include "DisplayManager.h"

namespace aura {

class SceneManager {
public:
    /// The high-level scenes. Only Idle shows the animated face.
    enum class Scene : uint8_t { Boot, Idle, Book, Shutdown };

    explicit SceneManager(DisplayManager& display) : _d(display) {}

    SceneManager(const SceneManager&)            = delete;
    SceneManager& operator=(const SceneManager&) = delete;

    // ---- lifecycle ----------------------------------------------------------

    /// Start the boot sequence (AURA logo + loading dots).
    void begin();

    /// Advance the active scene by `dtMs`. Non-blocking; call once per frame.
    void update(float dtMs);

    /// Return to the plain idle face scene, clearing the screen.
    void reset();

    // ---- scene commands -----------------------------------------------------

    void startBoot();

    /// Enter book/focus mode. FaceController should already have hidden the face
    /// (happy → shrink) before calling this; SceneManager then runs the book
    /// slide-in, page-turn loop, and (on stop) the close + slide-out.
    void startBookMode();

    /// Leave book mode. `celebrate` chooses whether a celebration is requested
    /// once the book has slid away (preserves the old FOCUS_DONE vs FOCUS_STOP
    /// distinction); FaceController reads celebrationRequested() to act on it.
    void stopBookMode(bool celebrate = true);

    /// Begin the shutdown animation.
    void startShutdown();

    /// Optional progress bar under the book while in the loop (0..1; <0 hides).
    void setProgress(float progress);

    // ---- queries ------------------------------------------------------------

    Scene currentScene() const { return _scene; }

    /// True when the face should be rendered this frame (Idle scene only).
    bool faceVisible() const { return _scene == Scene::Idle; }

    /// True for one poll after a transient scene (boot/book/shutdown) completes,
    /// so FaceController can react (show the face, celebrate, sleep). Cleared by
    /// the next scene command or reset().
    bool isSceneFinished() const { return _finished; }

    /// True if the finished book scene asked for a celebration.
    bool celebrationRequested() const { return _celebrationRequested; }

private:
    enum class BookPhase : uint8_t { SlideIn, Loop, Closing, SlideOut };

    // Per-scene update steps (keeps update() a small dispatcher, not a monolith).
    void updateBoot(float dtMs);
    void updateBook(float dtMs);
    void updateShutdown(float dtMs);

    // Drawing (all via DisplayManager).
    void drawBootLogo();
    void drawDots();
    void drawBook(int cx, int cy, float flipPhase, float closeAmt);
    void drawProgressBar(int cy);
    void drawThickLine(int x0, int y0, int x1, int y1, int thickness,
                       uint16_t color);
    void eraseBookRegion(int cy);

    // Book vertical slide (a tiny self-contained tween).
    void startSlide(float fromY, float toY, float ms, uint8_t easeId);
    void updateSlide(float dtMs);
    bool slideActive() const { return _slideActive; }

    DisplayManager& _d;

    Scene     _scene   = Scene::Boot;
    BookPhase _book    = BookPhase::SlideIn;
    uint32_t  _t       = 0;          ///< ms in the current scene/phase
    bool      _finished = false;
    bool      _celebrate = true;
    bool      _celebrationRequested = false;

    // Book state
    uint32_t _flipTimer = 0;
    float    _closeAmt  = 0.0f;
    float    _progress  = -1.0f;     ///< <0 hides the bar
    int      _prevBookY = kNoPrev;

    // Slide tween state
    float    _slideFrom = 0.0f, _slideTo = 0.0f, _slideCur = 0.0f;
    float    _slideElapsed = 0.0f, _slideDur = 1.0f;
    uint8_t  _slideEase = 0;
    bool     _slideActive = false;

    // Shutdown
    uint8_t  _startBrightness = cfg::backlight::defaultLevel;

    static constexpr int kNoPrev = -100000;
};

}  // namespace aura
