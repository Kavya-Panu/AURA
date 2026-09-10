// =============================================================================
//  face/EyeRenderer.cpp
// -----------------------------------------------------------------------------
//  Eye drawing algorithms, ported from the original firmware. The shapes and
//  proportions are unchanged; only the drawing target changed — everything now
//  goes through DisplayManager instead of a raw TFT sprite, and coordinates are
//  screen-relative rather than sprite-relative.
//
//  Self-contained: no math header is needed (the star uses a precomputed vertex
//  table and all other maths is integer/float arithmetic).
// =============================================================================
#include "EyeRenderer.h"

namespace aura {

namespace {
// Small, header-free numeric helpers (kept local to avoid pulling in <algorithm>
// or clashing with Arduino's min/max macros). Internal linkage — not globals.

inline int   imin(int a, int b)          { return a < b ? a : b; }
inline int   imax(int a, int b)          { return a > b ? a : b; }
inline void  iswap(int& a, int& b)       { int t = a; a = b; b = t; }
inline float absf(float v)               { return v < 0.0f ? -v : v; }
inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// Precomputed unit-circle vertices for a 5-point star: 10 points at 36° steps
// starting straight up (-90°). Using a fixed table means the star needs no
// runtime trigonometry (faster, and no dependency on a math header). Even
// indices are outer points, odd indices are inner points.
struct StarVertex { float cos; float sin; };
constexpr StarVertex kStarUnit[10] = {
    { 0.00000f, -1.00000f},   //  -90
    { 0.58779f, -0.80902f},   //  -54
    { 0.95106f, -0.30902f},   //  -18
    { 0.95106f,  0.30902f},   //   18
    { 0.58779f,  0.80902f},   //   54
    { 0.00000f,  1.00000f},   //   90
    {-0.58779f,  0.80902f},   //  126
    {-0.95106f,  0.30902f},   //  162
    {-0.95106f, -0.30902f},   //  198
    {-0.58779f, -0.80902f},   //  234
};
}  // namespace

// ---- public API -------------------------------------------------------------

void EyeRenderer::renderLeftEye(const EyeState& st) {
    const int half = static_cast<int>(cfg::eye::gap / 2 + cfg::eye::width / 2);
    render(st, cfg::display::width / 2 - half, cfg::eye::centerY);
}

void EyeRenderer::renderRightEye(const EyeState& st) {
    const int half = static_cast<int>(cfg::eye::gap / 2 + cfg::eye::width / 2);
    render(st, cfg::display::width / 2 + half, cfg::eye::centerY);
}

void EyeRenderer::render(const EyeState& st, int cx, int cy) {
    const EyeParams&      p = st.params;
    const AnimationState& a = st.anim;

    clipEye(cx);                       // erase previous frame in this eye's box
    cy += static_cast<int>(a.bob);     // apply breathing bob

    const float openFactor = clampf(p.openness * a.blink, 0.0f, 1.0f);

    // ---- celebrate star eye ----
    if (p.shape == EyeShape::Star) {
        drawStarEye(p, cx, cy, openFactor);
        return;
    }

    // ---- normal rounded-rect eye ----
    const int ew = static_cast<int>(p.width);
    const int eh = static_cast<int>(p.height * openFactor);

    if (eh < 6) {                      // (nearly) closed -> thin lid line
        drawClosedEye(cx, cy, ew, p.eyeColor);
        return;
    }

    drawEyeShape(p, st.eye, cx, cy, ew, eh);
    drawPupil(p, a, cx, cy, ew, eh);
}

// ---- private helpers --------------------------------------------------------

void EyeRenderer::clipEye(int cx) {
    // Clear a box sized to the eye's sprite footprint, centred on the canonical
    // eye Y so bob/blink extremes are always covered.
    const int w = cfg::sprite::eyeWidth;
    const int h = cfg::sprite::eyeHeight;
    _display.fillRect(cx - w / 2, cfg::eye::centerY - h / 2, w, h,
                      cfg::color::background);
}

void EyeRenderer::drawClosedEye(int cx, int cy, int ew, uint16_t color) {
    // Thin rounded bar representing a shut lid.
    _display.fillRoundRect(cx - ew / 2, cy - 2, ew, 4, 2, color);
}

void EyeRenderer::drawEyeShape(const EyeParams& p, Eye eye, int cx, int cy,
                               int ew, int eh) {
    const int r = imin(static_cast<int>(p.radius), imin(ew, eh) / 2);
    _display.fillRoundRect(cx - ew / 2, cy - eh / 2, ew, eh, r, p.eyeColor);

    // Emotion slant: angry cuts the inner-top corner, sad cuts the outer-top.
    if (absf(p.slant) > 0.01f) {
        const bool cutInner    = p.slant > 0.0f;
        const bool innerIsLeft = (eye == Eye::Right);
        const bool cutLeft     = cutInner ? innerIsLeft : !innerIsLeft;
        const float amt        = absf(p.slant);
        const int   dropY      = static_cast<int>(eh * 0.75f * amt);
        const int   top        = cy - eh / 2 - 1;
        const int   left       = cx - ew / 2 - 1;
        const int   right      = cx + ew / 2 + 1;
        if (cutLeft) {
            fillTriangle(left, top, right, top, left, top + dropY,
                         cfg::color::background);
        } else {
            fillTriangle(left, top, right, top, right, top + dropY,
                         cfg::color::background);
        }
    }

    // Happy crescent: carve a background circle up from the bottom of the eye.
    if (p.bottomArc > 0.01f) {
        const int carveR = static_cast<int>(eh * (0.9f + p.bottomArc * 0.8f));
        const int carveY = cy + eh / 2 +
                           static_cast<int>(carveR * (1.0f - p.bottomArc)) - 2;
        _display.fillCircle(cx, carveY, carveR, cfg::color::background);
    }
}

void EyeRenderer::drawPupil(const EyeParams& p, const AnimationState& a,
                            int cx, int cy, int ew, int eh) {
    if (p.pupil == PupilShape::None) {
        return;
    }
    const int pr = static_cast<int>(imin(ew, eh) * p.pupilScale * 0.5f);
    if (pr < 2) {
        return;
    }

    // Gaze is normalised (-1..1); map it to the pupil's travel range inside the
    // eye so the pupil never leaves the eye body.
    const int maxDX = ew / 2 - pr - 2;
    const int maxDY = eh / 2 - pr - 2;
    const int px = cx + static_cast<int>(clampf(a.gazeX, -1.0f, 1.0f) * maxDX);
    const int py = cy + static_cast<int>(clampf(a.gazeY, -1.0f, 1.0f) * maxDY);

    if (p.pupil == PupilShape::Heart) {
        drawHeartPupil(px, py, pr, p.pupilColor);
    } else {
        _display.fillCircle(px, py, pr, p.pupilColor);
        // Catch-light: a small highlight up-left of the pupil.
        _display.fillCircle(px - pr / 3, py - pr / 3, imax(1, pr / 5),
                            cfg::color::catchlight);
    }
}

void EyeRenderer::drawHeartPupil(int cx, int cy, int r, uint16_t color) {
    const int lobe = static_cast<int>(r * 0.55f);
    _display.fillCircle(cx - lobe, cy - lobe / 2, lobe, color);
    _display.fillCircle(cx + lobe, cy - lobe / 2, lobe, color);
    fillTriangle(cx - r, cy - lobe / 3, cx + r, cy - lobe / 3, cx, cy + r, color);
}

void EyeRenderer::drawStarEye(const EyeParams& p, int cx, int cy,
                              float openFactor) {
    if (openFactor < 0.08f) {          // blinked shut -> thin lid line
        _display.fillRoundRect(cx - 24, cy - 2, 48, 4, 2, p.eyeColor);
        return;
    }
    const float outer = imin(static_cast<int>(p.width),
                             static_cast<int>(p.height)) * 0.58f;
    drawStarShape(cx, cy, outer, openFactor, p.eyeColor);
}

void EyeRenderer::drawStarShape(int cx, int cy, float outer, float yScale,
                                uint16_t color) {
    // Fan-triangulate the star from its centre using the precomputed unit
    // vertices. Even indices use the outer radius, odd indices the inner one;
    // yScale squashes the star vertically so star-eyes can still "blink".
    const float inner = outer * 0.45f;

    float px = cx + kStarUnit[0].cos * outer;
    float py = cy + kStarUnit[0].sin * outer * yScale;
    for (int i = 1; i <= 10; ++i) {
        const int   idx = i % 10;                        // point 10 wraps to 0
        const float rr  = (i % 2 == 0) ? outer : inner;
        const float qx  = cx + kStarUnit[idx].cos * rr;
        const float qy  = cy + kStarUnit[idx].sin * rr * yScale;
        fillTriangle(cx, cy, static_cast<int>(px), static_cast<int>(py),
                     static_cast<int>(qx), static_cast<int>(qy), color);
        px = qx;
        py = qy;
    }
}

void EyeRenderer::fillTriangle(int x0, int y0, int x1, int y1, int x2, int y2,
                               uint16_t color) {
    // Sort vertices by ascending Y.
    if (y0 > y1) { iswap(x0, x1); iswap(y0, y1); }
    if (y0 > y2) { iswap(x0, x2); iswap(y0, y2); }
    if (y1 > y2) { iswap(x1, x2); iswap(y1, y2); }

    if (y0 == y2) {                    // fully degenerate (flat) triangle
        const int a = imin(x0, imin(x1, x2));
        const int b = imax(x0, imax(x1, x2));
        _display.drawLine(a, y0, b, y0, color);
        return;
    }

    // Interpolate an edge's X at scanline y.
    auto edgeX = [](int ya, int xa, int yb, int xb, int y) -> int {
        if (yb == ya) return xa;
        return xa + static_cast<int>(
                        static_cast<long>(xb - xa) * (y - ya) / (yb - ya));
    };

    for (int y = y0; y <= y2; ++y) {
        int xa = edgeX(y0, x0, y2, x2, y);             // long edge (y0..y2)
        int xb = (y < y1) ? edgeX(y0, x0, y1, x1, y)   // upper short edge
                          : edgeX(y1, x1, y2, x2, y);  // lower short edge
        if (xa > xb) iswap(xa, xb);
        _display.drawLine(xa, y, xb, y, color);
    }
}

}  // namespace aura
