// =============================================================================
//  face/MouthRenderer.cpp
// -----------------------------------------------------------------------------
//  Mouth drawing algorithms, ported from the original firmware. The shapes are
//  unchanged; only the drawing target changed — everything now goes through
//  DisplayManager instead of a raw TFT sprite, and coordinates are
//  screen-relative rather than sprite-relative.
//
//  Crescent mouths (smile/frown) are drawn the original way: a filled disc with
//  a second background disc subtracted to leave a curved band. Thick lines
//  (wavy/slant) are stamped from small circles since DisplayManager exposes no
//  wide-line primitive.
// =============================================================================
#include "MouthRenderer.h"

namespace aura {

namespace {
// Header-free numeric helpers (internal linkage — not globals).
inline int   imax(int a, int b) { return a > b ? a : b; }
inline int   iabs(int v)        { return v < 0 ? -v : v; }
inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

constexpr float kMinScale = 0.1f;
constexpr float kMaxScale = 3.0f;
}  // namespace

// ---- public API -------------------------------------------------------------

void MouthRenderer::setScale(float scale) {
    _scale = clampf(scale, kMinScale, kMaxScale);
}

void MouthRenderer::render(const MouthParams& m, uint16_t color) {
    drawMouth(m, cfg::display::width / 2, cfg::mouth::centerY, color);
}

void MouthRenderer::drawMouth(const MouthParams& m, int cx, int cy,
                              uint16_t color) {
    clearRegion(cx, cy);                       // erase previous frame

    const float w = m.width * _scale;

    switch (m.shape) {
        case MouthShape::None:                                    break;
        case MouthShape::Line:      drawLineMouth(w, cx, cy, color);      break;
        case MouthShape::Smile:     drawSmile(w, cx, cy, color);         break;
        case MouthShape::Sad:       drawSad(w, cx, cy, color);           break;
        case MouthShape::OpenSmile: drawOpenSmile(w, m.open, cx, cy, color); break;
        case MouthShape::Round:     drawRound(m.open, cx, cy, color);    break;
        case MouthShape::Wavy:      drawWavy(w, cx, cy, color);          break;
        case MouthShape::Slant:     drawSlant(w, cx, cy, color);         break;
    }
}

// ---- per-shape drawing ------------------------------------------------------

void MouthRenderer::drawLineMouth(float width, int cx, int cy, uint16_t color) {
    const int w = static_cast<int>(width);
    const int h = static_cast<int>(6 * _scale);
    _display.fillRoundRect(cx - w / 2, cy - h / 2, w, h, h / 2, color);
}

void MouthRenderer::drawSmile(float width, int cx, int cy, uint16_t color) {
    // Lower crescent (∪): a disc with a background disc subtracted from above.
    const int R     = static_cast<int>(width * 0.5f);
    const int thick = imax(static_cast<int>(6 * _scale),
                           static_cast<int>(R * 0.32f));
    const int cyC   = cy - static_cast<int>(R * 0.55f);
    _display.fillCircle(cx, cyC, R, color);
    _display.fillCircle(cx, cyC - thick, R, cfg::color::background);
}

void MouthRenderer::drawSad(float width, int cx, int cy, uint16_t color) {
    // Upper crescent (∩): mirror of the smile.
    const int R     = static_cast<int>(width * 0.5f);
    const int thick = imax(static_cast<int>(6 * _scale),
                           static_cast<int>(R * 0.32f));
    const int cyC   = cy + static_cast<int>(R * 0.55f);
    _display.fillCircle(cx, cyC, R, color);
    _display.fillCircle(cx, cyC + thick, R, cfg::color::background);
}

void MouthRenderer::drawOpenSmile(float width, float open, int cx, int cy,
                                  uint16_t color) {
    (void)color;

    const int outerW = static_cast<int>(width * (0.62f + 0.18f * open));
    const int outerH = static_cast<int>((22.0f + 24.0f * open) * _scale);
    const int x = cx - outerW / 2;
    const int y = cy - outerH / 2;

    // White mouth rim.
    _display.fillRoundRect(
        x, y, outerW, outerH, outerH / 2, cfg::color::catchlight
    );

    // Dark interior.
    const int border = imax(3, static_cast<int>(4 * _scale));
    _display.fillRoundRect(
        x + border,
        y + border,
        outerW - 2 * border,
        outerH - 2 * border,
        imax(2, outerH / 2 - border),
        cfg::color::background
    );

    // Pink tongue at the bottom.
    const int tongueW = outerW / 2;
    const int tongueH = imax(5, outerH / 5);
    _display.fillRoundRect(
        cx - tongueW / 2,
        y + outerH - border - tongueH,
        tongueW,
        tongueH,
        tongueH / 2,
        cfg::color::love
    );
}

void MouthRenderer::drawRound(float open, int cx, int cy, uint16_t color) {
    // Surprised "O": a ring (outer disc minus inner background disc).
    const int r = static_cast<int>((10 + 12 * open) * _scale);
    _display.fillCircle(cx, cy, r, color);
    _display.fillCircle(cx, cy, r / 2, cfg::color::background);
}

void MouthRenderer::drawWavy(float width, int cx, int cy, uint16_t color) {
    // Worried zigzag (~~~): four alternating diagonal thick segments.
    const int   w    = static_cast<int>(width);
    const int   seg  = 4;
    const float sw   = static_cast<float>(w) / seg;
    const int   amp  = static_cast<int>(5 * _scale);
    const int   thk  = static_cast<int>(5 * _scale);
    const int   x    = cx - w / 2;
    for (int i = 0; i < seg; ++i) {
        const int y0 = cy + ((i % 2) ? -amp : amp);
        const int y1 = cy + ((i % 2) ?  amp : -amp);
        drawThickLine(x + static_cast<int>(i * sw), y0,
                      x + static_cast<int>((i + 1) * sw), y1, thk, color);
    }
}

void MouthRenderer::drawSlant(float width, int cx, int cy, uint16_t color) {
    // "hmm" / confused: a single angled thick line.
    const int w   = static_cast<int>(width);
    const int amp = static_cast<int>(4 * _scale);
    const int thk = static_cast<int>(6 * _scale);
    drawThickLine(cx - w / 2, cy + amp, cx + w / 2, cy - amp, thk, color);
}

// ---- helpers ----------------------------------------------------------------

void MouthRenderer::clearRegion(int cx, int cy) {
    const int w = cfg::sprite::mouthWidth;
    const int h = cfg::sprite::mouthHeight;
    _display.fillRect(cx - w / 2, cy - h / 2, w, h, cfg::color::background);
}

void MouthRenderer::drawThickLine(int x0, int y0, int x1, int y1, int thickness,
                                  uint16_t color) {
    const int r  = imax(1, thickness / 2);
    const int dx = x1 - x0;
    const int dy = y1 - y0;
    const int steps = imax(1, imax(iabs(dx), iabs(dy)));
    for (int i = 0; i <= steps; ++i) {
        const int x = x0 + dx * i / steps;
        const int y = y0 + dy * i / steps;
        _display.fillCircle(x, y, r, color);       // rounded caps + body
    }
}

}  // namespace aura
