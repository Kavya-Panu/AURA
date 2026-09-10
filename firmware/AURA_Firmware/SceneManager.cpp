// =============================================================================
//  face/SceneManager.cpp
// -----------------------------------------------------------------------------
//  Scene state machine + non-face scene drawing. The book animation and boot
//  sequence are ported from the original firmware; the shapes and timing are
//  preserved, but drawing now goes through DisplayManager primitives (no raw
//  TFT, no sprites) and coordinates are screen-relative.
//
//  Emotion/animation cues that the old SceneManager performed inline (set happy,
//  shrink the face, celebrate) are intentionally NOT here — they belong to
//  FaceController, which polls this manager's scene state. This class only draws
//  scenes and reports where it is.
// =============================================================================
#include "SceneManager.h"

namespace aura {

namespace {
// ---- header-free numeric helpers (internal linkage) ------------------------
inline int   imin(int a, int b) { return a < b ? a : b; }
inline int   imax(int a, int b) { return a > b ? a : b; }
inline int   iabs(int v)        { return v < 0 ? -v : v; }
inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
inline float lerpf(float a, float b, float t) { return a + (b - a) * t; }

// Easing curves referenced by id (kept tiny; no Easing.h dependency).
enum EaseId : uint8_t { kOutBack = 0, kInOutCubic = 1 };
inline float easeOutBack(float t) {
    const float c1 = 1.70158f, c3 = c1 + 1.0f, f = t - 1.0f;
    return 1.0f + c3 * f * f * f + c1 * f * f;
}
inline float easeInOutCubic(float t) {
    if (t < 0.5f) return 4.0f * t * t * t;
    const float f = -2.0f * t + 2.0f;
    return 1.0f - (f * f * f) * 0.5f;
}
inline float applyEase(uint8_t id, float t) {
    return (id == kOutBack) ? easeOutBack(t) : easeInOutCubic(t);
}

// Scene timings not covered by Config (named, not scattered magic numbers).
constexpr uint32_t kBootMs        = 1900;
constexpr uint32_t kBookSlideInMs = 700;
constexpr uint32_t kBookCloseMs   = 650;
constexpr uint32_t kBookSlideOutMs = 600;
constexpr uint32_t kShutdownMs    = 700;

// Book geometry derived from the configured book footprint.
constexpr int kBW     = cfg::sprite::bookWidth;
constexpr int kBH     = cfg::sprite::bookHeight;
constexpr int kPageW  = (kBW - 22) / 2;
constexpr int kPageH  = kBH - 20;

inline int bookRestY() { return cfg::display::height / 2 - 8; }
inline int screenCx()  { return cfg::display::width / 2; }
}  // namespace

// ---- lifecycle --------------------------------------------------------------

void SceneManager::begin() { startBoot(); }

void SceneManager::reset() {
    _scene = Scene::Idle;
    _finished = false;
    _celebrationRequested = false;
    _slideActive = false;
    _prevBookY = kNoPrev;
    _d.clear();
}

// ---- scene commands ---------------------------------------------------------

void SceneManager::startBoot() {
    _scene = Scene::Boot;
    _t = 0;
    _finished = false;
    _d.clear();
    drawBootLogo();
}

void SceneManager::startBookMode() {
    _scene = Scene::Book;
    _book = BookPhase::SlideIn;
    _t = 0;
    _finished = false;
    _celebrationRequested = false;
    _closeAmt = 0.0f;
    _flipTimer = 0;
    _prevBookY = kNoPrev;
    _d.clear();
    // Slide up from just below the screen to the rest position (bouncy).
    startSlide(static_cast<float>(cfg::display::height + kBH / 2),
               static_cast<float>(bookRestY()), kBookSlideInMs, kOutBack);
}

void SceneManager::stopBookMode(bool celebrate) {
    if (_scene == Scene::Book &&
        (_book == BookPhase::SlideIn || _book == BookPhase::Loop)) {
        _celebrate = celebrate;
        _book = BookPhase::Closing;
        _t = 0;
    }
}

void SceneManager::startShutdown() {
    _scene = Scene::Shutdown;
    _t = 0;
    _finished = false;
    _startBrightness = _d.brightness();
}

void SceneManager::setProgress(float progress) {
    _progress = (progress < 0.0f) ? -1.0f : clampf(progress, 0.0f, 1.0f);
}

// ---- update dispatcher ------------------------------------------------------

void SceneManager::update(float dtMs) {
    if (dtMs < 0.0f) dtMs = 0.0f;
    _t += static_cast<uint32_t>(dtMs);

    switch (_scene) {
        case Scene::Boot:     updateBoot(dtMs);     break;
        case Scene::Idle:     /* FaceController draws the face */ break;
        case Scene::Book:     updateBook(dtMs);     break;
        case Scene::Shutdown: updateShutdown(dtMs); break;
    }
}

// ---- Boot -------------------------------------------------------------------

void SceneManager::updateBoot(float dtMs) {
    (void)dtMs;
    drawDots();
    if (_t >= kBootMs) {
        _d.clear();
        _scene = Scene::Idle;      // FaceController now pops the face in
        _finished = true;
        _t = 0;
    }
}

void SceneManager::drawBootLogo() {
    // "AURA" centred (DisplayManager text is top-left anchored, so offset by an
    // estimate of the string's size at this scale).
    const int size = 5;
    const int textW = 4 * 6 * size;    // 4 chars, ~6px glyph cell at size 1
    const int textH = 8 * size;
    _d.drawText(screenCx() - textW / 2, cfg::display::height / 2 - textH / 2,
                "AURA", cfg::color::eye, size);
}

void SceneManager::drawDots() {
    // Three loading dots cycling below the logo.
    const int cx = screenCx();
    const int y  = cfg::display::height / 2 + 34;
    const int lit = (_t / 320) % 4;                 // 0..3 dots lit
    const uint16_t dim = cfg::rgb565(30, 45, 60);
    for (int i = 0; i < 3; ++i) {
        const uint16_t c = (i < lit) ? cfg::color::eye : dim;
        _d.fillCircle(cx + (i - 1) * 26, y, 5, c);
    }
}

// ---- Book -------------------------------------------------------------------

void SceneManager::updateBook(float dtMs) {
    switch (_book) {
        case BookPhase::SlideIn:
            updateSlide(dtMs);
            drawBook(screenCx(), static_cast<int>(_slideCur), -1.0f, 0.0f);
            if (!slideActive()) { _book = BookPhase::Loop; _flipTimer = 0; }
            break;

        case BookPhase::Loop: {
            _flipTimer += static_cast<uint32_t>(dtMs);
            float flip = -1.0f;
            if (_flipTimer > cfg::book::flipEveryMs) {
                const uint32_t ft = _flipTimer - cfg::book::flipEveryMs;
                if (ft < cfg::book::flipMs)
                    flip = static_cast<float>(ft) / cfg::book::flipMs;
                else
                    _flipTimer = 0;
            }
            drawBook(screenCx(), bookRestY(), flip, 0.0f);
            drawProgressBar(bookRestY());
            break;
        }

        case BookPhase::Closing:
            _closeAmt = clampf(_t / static_cast<float>(kBookCloseMs), 0.0f, 1.0f);
            drawBook(screenCx(), bookRestY(), -1.0f, _closeAmt);
            if (_closeAmt >= 1.0f) {
                startSlide(static_cast<float>(bookRestY()),
                           static_cast<float>(cfg::display::height + kBH / 2),
                           kBookSlideOutMs, kInOutCubic);
                _book = BookPhase::SlideOut;
                _t = 0;
            }
            break;

        case BookPhase::SlideOut:
            updateSlide(dtMs);
            drawBook(screenCx(), static_cast<int>(_slideCur), -1.0f, 1.0f);
            if (!slideActive()) {
                _d.clear();
                _scene = Scene::Idle;
                _finished = true;
                _celebrationRequested = _celebrate;
                _t = 0;
            }
            break;
    }
}

void SceneManager::drawBook(int cx, int cy, float flipPhase, float closeAmt) {
    eraseBookRegion(cy);

    if (closeAmt >= 0.999f) {
        // Closed cover with an inset cyan frame and a tick mark.
        const int cw = kPageW + 14, ch = kPageH + 12;
        const int x = cx - cw / 2, y = cy - ch / 2;
        _d.fillRoundRect(x, y, cw, ch, 10, cfg::book::cover);
        _d.fillRoundRect(x + 5, y + 5, cw - 10, ch - 10, 7, cfg::color::eye);
        _d.fillRoundRect(x + 8, y + 8, cw - 16, ch - 16, 5, cfg::book::cover);
        drawThickLine(cx - 16, cy + 2, cx - 4, cy + 14, 5, cfg::color::eye);
        drawThickLine(cx - 4, cy + 14, cx + 18, cy - 12, 5, cfg::color::eye);
        _prevBookY = cy;
        return;
    }

    const int top = cy - kPageH / 2;
    // Cover slab behind the pages.
    _d.fillRoundRect(cx - kPageW - 8, top - 6, 2 * kPageW + 16, kPageH + 12, 8,
                     cfg::book::cover);
    // Left page (always full).
    _d.fillRoundRect(cx - kPageW, top, kPageW - 2, kPageH, 5, cfg::book::page);
    // Right page shrinks as the book closes.
    const int rw = static_cast<int>((kPageW - 2) * (1.0f - closeAmt));
    if (rw > 2)
        _d.fillRoundRect(cx + 2, top, rw, kPageH, 5, cfg::book::page);

    // Text lines on both pages.
    for (int i = 0; i < 5; ++i) {
        const int y = top + 16 + i * 20;
        _d.fillRect(cx - kPageW + 10, y, kPageW - 24, 3, cfg::book::line);
        if (rw > 30)
            _d.fillRect(cx + 12, y, imin(rw - 24, kPageW - 24), 3,
                        cfg::book::line);
    }

    // Spine.
    _d.fillRect(cx - 1, top, 2, kPageH, cfg::rgb565(60, 58, 50));

    // Turning page.
    if (flipPhase >= 0.0f && closeAmt < 0.01f) {
        if (flipPhase < 0.5f) {                        // lifting off the right
            const int w = static_cast<int>(kPageW * (1.0f - flipPhase * 2.0f));
            if (w > 3)
                _d.fillRoundRect(cx + 2, top - 2, w, kPageH, 5, cfg::book::flip);
        } else {                                       // landing on the left
            const int w = static_cast<int>(kPageW * ((flipPhase - 0.5f) * 2.0f));
            if (w > 3)
                _d.fillRoundRect(cx - w, top - 2, w, kPageH, 5, cfg::book::flip);
        }
    }

    _prevBookY = cy;
}

void SceneManager::drawProgressBar(int cy) {
    if (_progress < 0.0f) return;
    const int barW = 200, barH = 8;
    const int bx = screenCx() - barW / 2;
    const int by = cy + kBH / 2 + 10;
    // Track (thin border via two fills) + fill.
    _d.fillRoundRect(bx, by, barW, barH, 4, cfg::color::eye);
    _d.fillRoundRect(bx + 2, by + 2, barW - 4, barH - 4, 2,
                     cfg::color::background);
    const int fillW = static_cast<int>((barW - 4) * _progress);
    if (fillW > 0)
        _d.fillRoundRect(bx + 2, by + 2, fillW, barH - 4, 2, cfg::book::progress);
}

void SceneManager::eraseBookRegion(int cy) {
    // Clear the box the book last occupied so a moving book leaves no trail.
    const int x = screenCx() - kBW / 2;
    const int prev = (_prevBookY == kNoPrev) ? cy : _prevBookY;
    const int topMost = imin(prev, cy) - kBH / 2 - 2;
    const int height  = iabs(prev - cy) + kBH + 4;
    _d.fillRect(x - 2, topMost, kBW + 4, height, cfg::color::background);
}

// ---- Shutdown ---------------------------------------------------------------

void SceneManager::updateShutdown(float dtMs) {
    (void)dtMs;
    const float t = clampf(_t / static_cast<float>(kShutdownMs), 0.0f, 1.0f);

    // A bright line collapses horizontally to the centre while the backlight
    // dims, then the screen goes black.
    const int cx = screenCx();
    const int cy = cfg::display::height / 2;
    const int halfW = static_cast<int>((cfg::display::width / 2) * (1.0f - t));
    _d.fillRect(0, cy - 2, cfg::display::width, 4, cfg::color::background);
    if (halfW > 1)
        _d.fillRect(cx - halfW, cy - 2, halfW * 2, 4, cfg::color::eye);

    _d.setBrightness(static_cast<uint8_t>(_startBrightness * (1.0f - t)));

    if (t >= 1.0f) {
        _d.fillScreen(cfg::color::background);
        _finished = true;
    }
}

// ---- helpers ----------------------------------------------------------------

void SceneManager::drawThickLine(int x0, int y0, int x1, int y1, int thickness,
                                 uint16_t color) {
    const int r = imax(1, thickness / 2);
    const int dx = x1 - x0, dy = y1 - y0;
    const int steps = imax(1, imax(iabs(dx), iabs(dy)));
    for (int i = 0; i <= steps; ++i) {
        _d.fillCircle(x0 + dx * i / steps, y0 + dy * i / steps, r, color);
    }
}

void SceneManager::startSlide(float fromY, float toY, float ms, uint8_t easeId) {
    _slideFrom = fromY;
    _slideTo = toY;
    _slideCur = fromY;
    _slideElapsed = 0.0f;
    _slideDur = ms > 1.0f ? ms : 1.0f;
    _slideEase = easeId;
    _slideActive = true;
}

void SceneManager::updateSlide(float dtMs) {
    if (!_slideActive) return;
    _slideElapsed += dtMs;
    float t = _slideElapsed / _slideDur;
    if (t >= 1.0f) { t = 1.0f; _slideActive = false; }
    _slideCur = lerpf(_slideFrom, _slideTo, applyEase(_slideEase, t));
}

}  // namespace aura
