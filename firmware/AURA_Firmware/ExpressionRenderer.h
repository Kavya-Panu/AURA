#pragma once

#include <Arduino.h>

#include "Types.h"
#include "Config.h"
#include "DisplayManager.h"

namespace aura {

// Draws the complete face for each emotion using the approved AURA visual
// language. Blink timing is still supplied by BlinkSystem through
// AnimationState::blink; this class does not own or alter blink behaviour.
class ExpressionRenderer {
public:
    explicit ExpressionRenderer(DisplayManager& display) : _display(display) {}

    void begin();
    void reset();
    void setEmotion(Emotion emotion);
    void update(float dtMs);
    void render(Emotion emotion, const AnimationState& anim);

private:
    void drawNeutral(const AnimationState& anim);
    void drawHappy(const AnimationState& anim);
    void drawExcited(const AnimationState& anim);
    void drawSad(const AnimationState& anim);
    void drawAngry(const AnimationState& anim);
    void drawSurprised(const AnimationState& anim);
    void drawConfused(const AnimationState& anim);
    void drawCurious(const AnimationState& anim);
    void drawLove(const AnimationState& anim);
    void drawThinking(const AnimationState& anim);
    void drawListening(const AnimationState& anim);
    void drawSearching(const AnimationState& anim);
    void drawWorried(const AnimationState& anim);
    void drawCelebrate(const AnimationState& anim);
    void drawSleepy(const AnimationState& anim);
    void drawSleep(const AnimationState& anim);
    void drawError(const AnimationState& anim);

    void drawEye(int cx, int cy, int width, int height, float baseOpen,
                 float gazeX, float gazeY, float blink,
                 PupilShape pupil = PupilShape::Circle,
                 float pupilScale = 0.42f,
                 uint16_t eyeColor = cfg::color::eye,
                 uint16_t pupilColor = cfg::color::pupil,
                 bool happyArc = false,
                 bool sleepyLine = false);

    void drawHeart(int cx, int cy, int radius, uint16_t color);
    void drawSmile(int cx, int cy, int width, uint16_t color);
    void drawFrown(int cx, int cy, int width, uint16_t color);
    void drawLineMouth(int cx, int cy, int width, uint16_t color);
    void drawSlantMouth(int cx, int cy, int width, uint16_t color);
    void drawOpenSmile(int cx, int cy);
    void drawRoundMouth(int cx, int cy);
    void drawBlush();
    void drawThinkingDots();
    void drawQuestionMark();
    void drawSleepZs();
    void drawWorriedBrows();
    void drawAngryBrows();
    void drawStarPupil(int cx, int cy, int radius, uint16_t color);

    void drawThickLine(int x0, int y0, int x1, int y1,
                       int thickness, uint16_t color);
    void drawCurve(int x0, int y0, int controlX, int controlY,
                   int x1, int y1, int thickness, uint16_t color);
    void fillTriangle(int x0, int y0, int x1, int y1,
                      int x2, int y2, uint16_t color);

    DisplayManager& _display;
    Emotion _emotion = Emotion::Neutral;
    uint32_t _elapsedMs = 0;
};

}  // namespace aura
