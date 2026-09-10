// =============================================================================
//  face/MouthRenderer.h
// -----------------------------------------------------------------------------
//  Draws the mouth. That is its entire job.
//
//  MouthRenderer is a pure renderer: given a MouthParams (shape + width + open
//  amount) and a screen position, it draws that mouth. It DECIDES NO EMOTIONS,
//  ANIMATES NOTHING (including talking — the caller varies `open` over time and
//  this class simply draws the current value), does not blink, and touches no
//  hardware beyond DisplayManager. It never modifies the MouthParams it is given.
//
//  It reaches the screen ONLY through DisplayManager; it never names TFT_eSPI.
//
//  Allowed dependencies (and no others): core/Types.h, core/Config.h,
//  display/DisplayManager.h.
// =============================================================================
#pragma once

#include "Types.h"
#include "Config.h"
#include "DisplayManager.h"

namespace aura {

/// Renders a mouth from a MouthParams. Stateless with respect to the robot; its
/// only members are the injected display and a size scale.
class MouthRenderer {
public:
    /// Inject the display this renderer draws through (dependency injection).
    explicit MouthRenderer(DisplayManager& display) : _display(display) {}

    MouthRenderer(const MouthRenderer&)            = delete;
    MouthRenderer& operator=(const MouthRenderer&) = delete;

    // ---- public API ---------------------------------------------------------

    /// Render the mouth at its canonical on-screen position (from Config).
    /// `color` defaults to the face colour; the caller may pass the current
    /// emotion's colour (e.g. red for Error). Does not modify `m`.
    void render(const MouthParams& m, uint16_t color = cfg::color::eye);

    /// Draw the mouth centred at an explicit screen coordinate.
    void drawMouth(const MouthParams& m, int cx, int cy, uint16_t color);

    /// Scale the whole mouth (1.0 = normal). Clamped to a sane range.
    void setScale(float scale);

private:
    // Per-shape drawing helpers — each reads MouthParams, draws via _display.
    void drawLineMouth(float width, int cx, int cy, uint16_t color);
    void drawSmile(float width, int cx, int cy, uint16_t color);
    void drawSad(float width, int cx, int cy, uint16_t color);
    void drawOpenSmile(float width, float open, int cx, int cy, uint16_t color);
    void drawRound(float open, int cx, int cy, uint16_t color);
    void drawWavy(float width, int cx, int cy, uint16_t color);
    void drawSlant(float width, int cx, int cy, uint16_t color);

    /// Erase the mouth's bounding region before redrawing (clears last frame).
    void clearRegion(int cx, int cy);

    /// Thick line via stamped circles (DisplayManager has no wide-line
    /// primitive), giving rounded caps. Used by wavy and slant mouths.
    void drawThickLine(int x0, int y0, int x1, int y1, int thickness,
                       uint16_t color);

    DisplayManager& _display;     ///< injected; the only way this class draws
    float           _scale = 1.0f;
};

}  // namespace aura
