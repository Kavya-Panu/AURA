#include "ExpressionRenderer.h"

namespace aura {

namespace {
constexpr int kLeftEyeX  = 96;
constexpr int kRightEyeX = 224;
constexpr int kEyeY      = 92;
constexpr int kMouthY    = 184;

constexpr int kEyeWidth  = 72;
constexpr int kEyeHeight = 80;

constexpr uint16_t kWhite = cfg::color::catchlight;
constexpr uint16_t kBlack = cfg::color::background;
constexpr uint16_t kBlue  = cfg::color::eye;
constexpr uint16_t kPink  = cfg::color::love;

inline int imax(int a, int b) { return a > b ? a : b; }
inline int imin(int a, int b) { return a < b ? a : b; }
inline int iabs(int v) { return v < 0 ? -v : v; }
inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
}

void ExpressionRenderer::begin() { reset(); }

void ExpressionRenderer::reset() {
    _emotion = Emotion::Neutral;
    _elapsedMs = 0;
}

void ExpressionRenderer::setEmotion(Emotion emotion) {
    if (_emotion != emotion) {
        _emotion = emotion;
        _elapsedMs = 0;
    }
}

void ExpressionRenderer::update(float dtMs) {
    if (dtMs > 0.0f) {
        _elapsedMs += static_cast<uint32_t>(dtMs);
    }
}

void ExpressionRenderer::render(Emotion emotion, const AnimationState& anim) {
    setEmotion(emotion);

    switch (emotion) {
        case Emotion::Neutral:   drawNeutral(anim); break;
        case Emotion::Happy:     drawHappy(anim); break;
        case Emotion::Excited:   drawExcited(anim); break;
        case Emotion::Sad:       drawSad(anim); break;
        case Emotion::Angry:     drawAngry(anim); break;
        case Emotion::Surprised: drawSurprised(anim); break;
        case Emotion::Confused:  drawConfused(anim); break;
        case Emotion::Curious:   drawCurious(anim); break;
        case Emotion::Love:      drawLove(anim); break;
        case Emotion::Thinking:  drawThinking(anim); break;
        case Emotion::Listening: drawListening(anim); break;
        case Emotion::Searching: drawThinking(anim); break;
        case Emotion::Worried:   drawWorried(anim); break;
        case Emotion::Celebrate: drawCelebrate(anim); break;
        case Emotion::Sleepy:    drawSleepy(anim); break;
        case Emotion::Sleep:     drawSleep(anim); break;
        case Emotion::Error:     drawError(anim); break;
    }
}

void ExpressionRenderer::drawNeutral(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, kEyeWidth, kEyeHeight, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink);
    drawEye(kRightEyeX, kEyeY, kEyeWidth, kEyeHeight, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink);
    drawLineMouth(160, kMouthY, 38, kWhite);
}

void ExpressionRenderer::drawHappy(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 74, 76, 0.92f,
            0.0f, 0.0f, anim.blink, PupilShape::None,
            0.0f, kBlue, kBlack, true, false);
    drawEye(kRightEyeX, kEyeY, 74, 76, 0.92f,
            0.0f, 0.0f, anim.blink, PupilShape::None,
            0.0f, kBlue, kBlack, true, false);
    drawSmile(160, 176, 82, kWhite);
}

void ExpressionRenderer::drawExcited(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 76, 84, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.42f);
    drawEye(kRightEyeX, kEyeY, 76, 84, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.42f);
    drawBlush();
    drawOpenSmile(160, 181);
}

void ExpressionRenderer::drawSad(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY + 3, 70, 76, 0.92f,
            anim.gazeX, 0.25f, anim.blink, PupilShape::Circle, 0.38f);
    drawEye(kRightEyeX, kEyeY + 3, 70, 76, 0.92f,
            anim.gazeX, 0.25f, anim.blink, PupilShape::Circle, 0.38f);
    drawWorriedBrows();
    drawFrown(160, 190, 72, kWhite);
}

void ExpressionRenderer::drawAngry(const AnimationState& anim) {
    (void)anim;  // BlinkSystem is unchanged; angry uses animated flame eyes.

    // Flicker phase changes the height and side tongues without random numbers,
    // so the animation is smooth and deterministic.
    const uint32_t phase = (_elapsedMs / 110U) % 6U;

    const uint16_t flameRed    = cfg::rgb565(255, 32, 20);
    const uint16_t flameOrange = cfg::rgb565(255, 125, 0);
    const uint16_t flameYellow = cfg::rgb565(255, 225, 35);

    auto drawFlameEye = [&](int cx, int baseY, uint32_t offset) {
        const uint32_t localPhase = (phase + offset) % 6U;

        const int flicker =
            (localPhase == 0U || localPhase == 5U) ? 0 :
            (localPhase == 1U || localPhase == 4U) ? 5 : 9;

        const int topY = baseY - 70 - flicker;

        // Outer red flame body.
        _display.fillCircle(cx, baseY - 20, 25, flameRed);
        _display.fillCircle(cx - 13, baseY - 28, 16, flameRed);
        _display.fillCircle(cx + 13, baseY - 27, 16, flameRed);

        fillTriangle(cx - 25, baseY - 15,
                     cx - 13, baseY - 58 - flicker / 2,
                     cx - 2,  baseY - 18,
                     flameRed);

        fillTriangle(cx - 8,  baseY - 18,
                     cx,      topY,
                     cx + 10, baseY - 18,
                     flameRed);

        fillTriangle(cx + 4,  baseY - 17,
                     cx + 18, baseY - 55 + flicker / 3,
                     cx + 27, baseY - 14,
                     flameRed);

        // Orange middle flame.
        _display.fillCircle(cx, baseY - 17, 18, flameOrange);
        fillTriangle(cx - 17, baseY - 14,
                     cx - 7,  baseY - 47 - flicker / 3,
                     cx + 1,  baseY - 13,
                     flameOrange);

        fillTriangle(cx - 4, baseY - 12,
                     cx + 4, baseY - 55 - flicker / 2,
                     cx + 14, baseY - 12,
                     flameOrange);

        // Yellow hot core.
        _display.fillCircle(cx, baseY - 12, 12, flameYellow);
        fillTriangle(cx - 11, baseY - 10,
                     cx,      baseY - 39 - flicker / 4,
                     cx + 11, baseY - 10,
                     flameYellow);
    };

    drawFlameEye(kLeftEyeX, 139, 0U);
    drawFlameEye(kRightEyeX, 139, 3U);

    // Keep the approved angry eyebrows.
    drawAngryBrows();

    // Keep the angry frown.
    drawFrown(160, 196, 70, kWhite);
}

void ExpressionRenderer::drawSurprised(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY - 2, 78, 88, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.32f);
    drawEye(kRightEyeX, kEyeY - 2, 78, 88, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.32f);
    drawRoundMouth(160, 183);
}

void ExpressionRenderer::drawConfused(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY + 5, 66, 70, 0.92f,
            -0.25f, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.38f);
    drawEye(kRightEyeX, kEyeY - 2, 78, 84, 1.0f,
            0.25f, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.38f);
    drawQuestionMark();
    drawSlantMouth(160, 187, 48, kWhite);
}

void ExpressionRenderer::drawCurious(const AnimationState& anim) {
    const uint32_t phase = _elapsedMs % 1800U;
    float autoX;
    if (phase < 900U) {
        autoX = -0.65f + 1.30f * (static_cast<float>(phase) / 900.0f);
    } else {
        autoX = 0.65f - 1.30f * (static_cast<float>(phase - 900U) / 900.0f);
    }
    const float gazeX = (anim.gazeX > 0.20f || anim.gazeX < -0.20f)
                      ? anim.gazeX : autoX;

    drawEye(kLeftEyeX, kEyeY, 72, 80, 1.0f,
            gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.40f);
    drawEye(kRightEyeX, kEyeY, 72, 80, 1.0f,
            gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.40f);
    drawRoundMouth(160, 183);
}

void ExpressionRenderer::drawLove(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 76, 82, 1.0f,
            0.0f, 0.0f, anim.blink,
            PupilShape::Heart, 0.54f, kBlue, kPink);
    drawEye(kRightEyeX, kEyeY, 76, 82, 1.0f,
            0.0f, 0.0f, anim.blink,
            PupilShape::Heart, 0.54f, kBlue, kPink);
    drawBlush();
    drawSmile(160, 178, 78, kWhite);
}

void ExpressionRenderer::drawThinking(const AnimationState& anim) {
    // Keep both eyes in the normal AURA style, looking up-right.
    drawEye(kLeftEyeX, kEyeY, 72, 80, 0.96f,
            0.42f, -0.72f, anim.blink,
            PupilShape::Circle, 0.36f);
    drawEye(kRightEyeX, kEyeY, 72, 80, 0.96f,
            0.42f, -0.72f, anim.blink,
            PupilShape::Circle, 0.36f);

    // Processing animation above the right eye:
    // . -> .. -> ... -> .... -> .
    drawThinkingDots();

    // Small straight mouth tilted by about 30 degrees.
    drawThickLine(142, 193,
                  178, 172,
                  5, kWhite);
}

void ExpressionRenderer::drawListening(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 74, 82, 1.0f,
            anim.gazeX * 0.25f, anim.gazeY * 0.25f, anim.blink,
            PupilShape::Circle, 0.42f);
    drawEye(kRightEyeX, kEyeY, 74, 82, 1.0f,
            anim.gazeX * 0.25f, anim.gazeY * 0.25f, anim.blink,
            PupilShape::Circle, 0.42f);
    drawSmile(160, 180, 56, kWhite);
}

void ExpressionRenderer::drawSearching(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 74, 80, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.38f);
    drawEye(kRightEyeX, kEyeY, 74, 80, 1.0f,
            anim.gazeX, anim.gazeY, anim.blink,
            PupilShape::Circle, 0.38f);
    drawLineMouth(160, kMouthY, 44, kWhite);
}

void ExpressionRenderer::drawWorried(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY + 3, 70, 76, 0.94f,
            anim.gazeX, 0.15f, anim.blink,
            PupilShape::Circle, 0.39f);
    drawEye(kRightEyeX, kEyeY + 3, 70, 76, 0.94f,
            anim.gazeX, 0.15f, anim.blink,
            PupilShape::Circle, 0.39f);
    drawWorriedBrows();
    drawFrown(160, 190, 70, kWhite);
}

void ExpressionRenderer::drawCelebrate(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 76, 84, 1.0f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f);
    drawEye(kRightEyeX, kEyeY, 76, 84, 1.0f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f);
    drawStarPupil(kLeftEyeX, kEyeY, 20, cfg::color::star);
    drawStarPupil(kRightEyeX, kEyeY, 20, cfg::color::star);
    drawBlush();
    drawOpenSmile(160, 181);
}

void ExpressionRenderer::drawSleepy(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 74, 72, 0.62f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f, kBlue, kBlack,
            false, true);
    drawEye(kRightEyeX, kEyeY, 74, 72, 0.62f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f, kBlue, kBlack,
            false, true);
    drawSleepZs();
    drawLineMouth(160, kMouthY, 38, kWhite);
}

void ExpressionRenderer::drawSleep(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 70, 70, 0.08f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f);
    drawEye(kRightEyeX, kEyeY, 70, 70, 0.08f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f);
    drawSleepZs();
}

void ExpressionRenderer::drawError(const AnimationState& anim) {
    drawEye(kLeftEyeX, kEyeY, 72, 70, 0.75f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f, cfg::color::error);
    drawEye(kRightEyeX, kEyeY, 72, 70, 0.75f,
            0.0f, 0.0f, anim.blink,
            PupilShape::None, 0.0f, cfg::color::error);
    drawFrown(160, 190, 70, cfg::color::error);
}

void ExpressionRenderer::drawEye(int cx, int cy, int width, int height,
                                 float baseOpen, float gazeX, float gazeY,
                                 float blink, PupilShape pupil,
                                 float pupilScale, uint16_t eyeColor,
                                 uint16_t pupilColor, bool happyArc,
                                 bool sleepyLine) {
    const float open = clampf(baseOpen * blink, 0.0f, 1.0f);
    const int currentH = imax(4, static_cast<int>(height * open));

    if (open < 0.10f) {
        _display.fillRoundRect(cx - width / 2, cy - 3,
                               width, 6, 3, eyeColor);
        return;
    }

    const int radius = imin(24, currentH / 2);
    _display.fillRoundRect(cx - width / 2, cy - currentH / 2,
                           width, currentH, radius, eyeColor);

    if (happyArc) {
        drawCurve(cx - 20, cy + 7,
                  cx, cy - 13,
                  cx + 20, cy + 7,
                  5, kBlack);
        return;
    }

    if (sleepyLine) {
        drawCurve(cx - 22, cy + 2,
                  cx, cy + 8,
                  cx + 22, cy + 2,
                  5, kBlack);
        return;
    }

    if (pupil == PupilShape::None) {
        return;
    }

    const int pupilR = imax(5, static_cast<int>(imin(width, currentH)
                                                * pupilScale * 0.5f));
    const int maxDx = imax(0, width / 2 - pupilR - 5);
    const int maxDy = imax(0, currentH / 2 - pupilR - 5);
    const int px = cx + static_cast<int>(clampf(gazeX, -1.0f, 1.0f) * maxDx);
    const int py = cy + static_cast<int>(clampf(gazeY, -1.0f, 1.0f) * maxDy);

    if (pupil == PupilShape::Heart) {
        drawHeart(px, py, pupilR, pupilColor);
    } else {
        _display.fillCircle(px, py, pupilR, pupilColor);
        _display.fillCircle(px - pupilR / 3,
                            py - pupilR / 3,
                            imax(2, pupilR / 5),
                            kWhite);
    }
}

void ExpressionRenderer::drawHeart(int cx, int cy, int radius,
                                   uint16_t color) {
    const int lobe = imax(3, radius / 2);
    _display.fillCircle(cx - lobe, cy - lobe / 2, lobe, color);
    _display.fillCircle(cx + lobe, cy - lobe / 2, lobe, color);
    fillTriangle(cx - radius, cy,
                 cx + radius, cy,
                 cx, cy + radius + 5,
                 color);
}

void ExpressionRenderer::drawSmile(int cx, int cy, int width,
                                   uint16_t color) {
    drawCurve(cx - width / 2, cy - 5,
              cx, cy + 22,
              cx + width / 2, cy - 5,
              5, color);
}

void ExpressionRenderer::drawFrown(int cx, int cy, int width,
                                   uint16_t color) {
    drawCurve(cx - width / 2, cy + 6,
              cx, cy - 18,
              cx + width / 2, cy + 6,
              5, color);
}

void ExpressionRenderer::drawLineMouth(int cx, int cy, int width,
                                       uint16_t color) {
    drawThickLine(cx - width / 2, cy, cx + width / 2, cy, 5, color);
}

void ExpressionRenderer::drawSlantMouth(int cx, int cy, int width,
                                        uint16_t color) {
    drawThickLine(cx - width / 2, cy + 7,
                  cx + width / 2, cy - 7,
                  5, color);
}

void ExpressionRenderer::drawOpenSmile(int cx, int cy) {
    constexpr int outerW = 76;
    constexpr int outerH = 44;
    constexpr int border = 5;

    _display.fillRoundRect(cx - outerW / 2, cy - outerH / 2,
                           outerW, outerH, 20, kWhite);
    _display.fillRoundRect(cx - outerW / 2 + border,
                           cy - outerH / 2 + border,
                           outerW - 2 * border,
                           outerH - 2 * border,
                           16, kBlack);
    _display.fillRoundRect(cx - 22, cy + 5,
                           44, 10, 5, kPink);
}

void ExpressionRenderer::drawRoundMouth(int cx, int cy) {
    _display.fillCircle(cx, cy, 11, kWhite);
    _display.fillCircle(cx, cy, 6, kBlack);
}

void ExpressionRenderer::drawBlush() {
    for (int i = 0; i < 3; ++i) {
        _display.fillCircle(62 + i * 8, 145, 3, kPink);
        _display.fillCircle(242 + i * 8, 145, 3, kPink);
    }
}

void ExpressionRenderer::drawThinkingDots() {
    const int count = static_cast<int>((_elapsedMs / 400U) % 4U) + 1;
    constexpr int startX = 202;
    constexpr int y = 28;
    constexpr int radius = 4;
    constexpr int spacing = 16;

    for (int i = 0; i < count; ++i) {
        _display.fillCircle(startX + i * spacing, y, radius, kWhite);
    }
}

void ExpressionRenderer::drawQuestionMark() {
    _display.drawText(265, 20, "?", kWhite, 3);
}

void ExpressionRenderer::drawSleepZs() {
    const int drift = static_cast<int>((_elapsedMs / 500U) % 2U) * 2;
    _display.drawText(238 + drift, 50 - drift, "z", kWhite, 1);
    _display.drawText(254 + drift, 34 - drift, "Z", kWhite, 2);
    _display.drawText(280 + drift, 12 - drift, "Z", kWhite, 3);
}

void ExpressionRenderer::drawWorriedBrows() {
    drawThickLine(62, 52, 108, 65, 5, kWhite);
    drawThickLine(212, 65, 258, 52, 5, kWhite);
}

void ExpressionRenderer::drawAngryBrows() {
    drawThickLine(62, 45, 112, 67, 5, kWhite);
    drawThickLine(208, 67, 258, 45, 5, kWhite);
}

void ExpressionRenderer::drawStarPupil(int cx, int cy, int radius,
                                       uint16_t color) {
    // Compact sparkle made from one centre circle and four pointed triangles.
    _display.fillCircle(cx, cy, radius / 2, color);
    fillTriangle(cx, cy - radius,
                 cx - radius / 3, cy - radius / 3,
                 cx + radius / 3, cy - radius / 3,
                 color);
    fillTriangle(cx, cy + radius,
                 cx - radius / 3, cy + radius / 3,
                 cx + radius / 3, cy + radius / 3,
                 color);
    fillTriangle(cx - radius, cy,
                 cx - radius / 3, cy - radius / 3,
                 cx - radius / 3, cy + radius / 3,
                 color);
    fillTriangle(cx + radius, cy,
                 cx + radius / 3, cy - radius / 3,
                 cx + radius / 3, cy + radius / 3,
                 color);
}

void ExpressionRenderer::drawThickLine(int x0, int y0, int x1, int y1,
                                       int thickness, uint16_t color) {
    const int radius = imax(1, thickness / 2);
    const int dx = x1 - x0;
    const int dy = y1 - y0;
    const int steps = imax(1, imax(iabs(dx), iabs(dy)));

    for (int i = 0; i <= steps; ++i) {
        _display.fillCircle(x0 + dx * i / steps,
                            y0 + dy * i / steps,
                            radius,
                            color);
    }
}

void ExpressionRenderer::drawCurve(int x0, int y0,
                                   int controlX, int controlY,
                                   int x1, int y1,
                                   int thickness, uint16_t color) {
    constexpr int steps = 32;
    int previousX = x0;
    int previousY = y0;

    for (int i = 1; i <= steps; ++i) {
        const float t = static_cast<float>(i) / steps;
        const float u = 1.0f - t;
        const int x = static_cast<int>(u * u * x0
                                    + 2.0f * u * t * controlX
                                    + t * t * x1);
        const int y = static_cast<int>(u * u * y0
                                    + 2.0f * u * t * controlY
                                    + t * t * y1);
        drawThickLine(previousX, previousY, x, y, thickness, color);
        previousX = x;
        previousY = y;
    }
}

void ExpressionRenderer::fillTriangle(int x0, int y0, int x1, int y1,
                                      int x2, int y2, uint16_t color) {
    // Barycentric scan over a small bounding box. Used only for hearts/stars.
    const int minX = imin(x0, imin(x1, x2));
    const int maxX = imax(x0, imax(x1, x2));
    const int minY = imin(y0, imin(y1, y2));
    const int maxY = imax(y0, imax(y1, y2));

    const long area = static_cast<long>(x1 - x0) * (y2 - y0)
                    - static_cast<long>(y1 - y0) * (x2 - x0);
    if (area == 0) {
        return;
    }

    for (int y = minY; y <= maxY; ++y) {
        for (int x = minX; x <= maxX; ++x) {
            const long w0 = static_cast<long>(x1 - x0) * (y - y0)
                          - static_cast<long>(y1 - y0) * (x - x0);
            const long w1 = static_cast<long>(x2 - x1) * (y - y1)
                          - static_cast<long>(y2 - y1) * (x - x1);
            const long w2 = static_cast<long>(x0 - x2) * (y - y2)
                          - static_cast<long>(y0 - y2) * (x - x2);

            const bool inside = area > 0
                              ? (w0 >= 0 && w1 >= 0 && w2 >= 0)
                              : (w0 <= 0 && w1 <= 0 && w2 <= 0);
            if (inside) {
                _display.drawPixel(x, y, color);
            }
        }
    }
}

}  // namespace aura
