// =============================================================================
//  face/EyeRenderer.h
// -----------------------------------------------------------------------------
//  Draws eyes. That is its entire job.
//
//  EyeRenderer is a pure renderer: given a fully-resolved EyeState (shape +
//  this-frame animation) and a screen position, it puts the eye on the panel.
//  It DECIDES NOTHING — no emotions, no blink timing, no gaze targets, no
//  animation, no robot state. Those are computed elsewhere and arrive baked
//  into the EyeState it is handed. It never modifies that EyeState.
//
//  It reaches the screen ONLY through DisplayManager; it never touches TFT_eSPI,
//  never owns the display, and never initialises hardware.
//
//  Allowed dependencies (and no others): core/Types.h, core/Config.h,
//  display/DisplayManager.h.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"
#include "DisplayManager.h"

namespace aura {

/// Renders a single eye from an EyeState. Stateless with respect to the robot;
/// its only member is the injected display it draws through.
class EyeRenderer {
public:
    /// Inject the display this renderer draws through (dependency injection).
    explicit EyeRenderer(DisplayManager& display) : _display(display) {}

    // Non-copyable: it holds a reference to a hardware-owning object.
    EyeRenderer(const EyeRenderer&)            = delete;
    EyeRenderer& operator=(const EyeRenderer&) = delete;

    // ---- public API ---------------------------------------------------------

    /// Render one eye centred at screen coordinate (cx, cy). The vertical
    /// breathing bob in the state is applied on top of cy. Does not modify `st`.
    void render(const EyeState& st, int cx, int cy);

    /// Render the left eye at its canonical on-screen position (from Config).
    void renderLeftEye(const EyeState& st);

    /// Render the right eye at its canonical on-screen position (from Config).
    void renderRightEye(const EyeState& st);

private:
    // ---- private drawing helpers (not part of the public surface) -----------

    /// Paint the eye's bounding region back to the background, erasing the
    /// previous frame before the new eye is drawn.
    void clipEye(int cx);

    /// Draw the normal rounded-rect eye body, including emotion slant carve and
    /// the happy-crescent carve.
    void drawEyeShape(const EyeParams& p, Eye eye, int cx, int cy,
                      int ew, int eh);

    /// Draw the celebrate star-eye (fan-triangulated 5-point star).
    void drawStarEye(const EyeParams& p, int cx, int cy, float openFactor);

    /// Draw the thin closed-lid line used when the eye is (nearly) shut.
    void drawClosedEye(int cx, int cy, int ew, uint16_t color);

    /// Draw the pupil (circle + catch-light, or heart) offset by gaze.
    void drawPupil(const EyeParams& p, const AnimationState& a,
                   int cx, int cy, int ew, int eh);

    /// Draw a heart-shaped pupil centred at (cx, cy) with radius r.
    void drawHeartPupil(int cx, int cy, int r, uint16_t color);

    /// Filled 5-point star, fan-triangulated from the centre; yScale squashes it
    /// vertically so star-eyes can still "blink".
    void drawStarShape(int cx, int cy, float outer, float yScale,
                       uint16_t color);

    /// Filled triangle via horizontal scanlines (DisplayManager has no triangle
    /// primitive, so we build one from drawLine — public API only).
    void fillTriangle(int x0, int y0, int x1, int y1, int x2, int y2,
                      uint16_t color);

    DisplayManager& _display;   ///< injected; the only way this class draws
};

}  // namespace aura
