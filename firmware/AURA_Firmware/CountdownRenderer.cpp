// =============================================================================
// CountdownRenderer.cpp
// =============================================================================
#include "CountdownRenderer.h"
#include "Config.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace aura {

namespace {
constexpr uint16_t kCyan   = cfg::rgb565(50, 220, 255);
constexpr uint16_t kBlue   = cfg::rgb565(30, 90, 210);
constexpr uint16_t kWhite  = cfg::rgb565(255, 255, 255);
constexpr uint16_t kMuted  = cfg::rgb565(120, 145, 160);
constexpr uint16_t kOrange = cfg::rgb565(255, 135, 20);
constexpr uint16_t kRed    = cfg::rgb565(255, 45, 35);
constexpr float kPi = 3.14159265358979323846f;
}

void CountdownRenderer::start(uint32_t seconds, const char* kind) {
    _durationSeconds = seconds > 0 ? seconds : 1;
    _startedAtMs = millis();
    copyKind(kind);
    _mode = Mode::Countdown;
}

void CountdownRenderer::alert(const char* kind) {
    copyKind(kind);
    _mode = Mode::Alert;
}

void CountdownRenderer::stop() {
    _mode = Mode::Hidden;
    _durationSeconds = 0;
    _startedAtMs = 0;
    copyKind("TIMER");
}

uint32_t CountdownRenderer::remainingSeconds() const {
    if (_mode != Mode::Countdown || _durationSeconds == 0) return 0;
    const uint32_t elapsedMs = millis() - _startedAtMs;
    const uint32_t elapsedSeconds = elapsedMs / 1000UL;
    if (elapsedSeconds >= _durationSeconds) return 0;
    return _durationSeconds - elapsedSeconds;
}

void CountdownRenderer::render() {
    _display.clear();
    if (_mode == Mode::Alert) {
        drawAlert();
        return;
    }
    if (_mode == Mode::Countdown) {
        drawCountdown(remainingSeconds());
    }
}

void CountdownRenderer::drawCountdown(uint32_t remaining) {
    const float ratio = _durationSeconds > 0
        ? static_cast<float>(remaining) / static_cast<float>(_durationSeconds)
        : 0.0f;
    uint16_t accent = kCyan;
    if (remaining <= 10) {
        accent = ((millis() / 250UL) % 2UL) ? kOrange : kRed;
    }

    const int kindWidth = static_cast<int>(strlen(_kind)) * 12;
    _display.drawText(160 - kindWidth / 2, 12, _kind, kMuted, 2);
    drawProgressRing(ratio, accent);

    char timeText[16] = {};
    uint8_t size = 5;
    if (remaining >= 3600) {
        const uint32_t hours = remaining / 3600UL;
        const uint32_t minutes = (remaining / 60UL) % 60UL;
        const uint32_t seconds = remaining % 60UL;
        snprintf(timeText, sizeof(timeText), "%lu:%02lu:%02lu",
                 static_cast<unsigned long>(hours),
                 static_cast<unsigned long>(minutes),
                 static_cast<unsigned long>(seconds));
        size = 3;
    } else {
        const uint32_t minutes = remaining / 60UL;
        const uint32_t seconds = remaining % 60UL;
        snprintf(timeText, sizeof(timeText), "%02lu:%02lu",
                 static_cast<unsigned long>(minutes),
                 static_cast<unsigned long>(seconds));
    }
    const int textWidth = static_cast<int>(strlen(timeText)) * 6 * size;
    _display.drawText(160 - textWidth / 2, 103, timeText, kWhite, size);

    const char* caption = "REMAINING";
    _display.drawText(160 - 27, 205, caption, kMuted, 1);
}

void CountdownRenderer::drawAlert() {
    const bool phase = ((millis() / 220UL) % 2UL) != 0;
    const uint16_t accent = phase ? kRed : kOrange;
    drawProgressRing(1.0f, accent);

    const int kindWidth = static_cast<int>(strlen(_kind)) * 12;
    _display.drawText(160 - kindWidth / 2, 28, _kind, accent, 2);
    _display.drawText(61, 100, "TIME'S UP!", kWhite, 3);
    _display.drawText(103, 164, "AURA ALERT", accent, 2);
}

void CountdownRenderer::drawProgressRing(float ratio, uint16_t color) {
    if (ratio < 0.0f) ratio = 0.0f;
    if (ratio > 1.0f) ratio = 1.0f;
    constexpr int segments = 60;
    const int lit = static_cast<int>(ratio * segments + 0.5f);
    for (int i = 0; i < segments; ++i) {
        const float angle = -kPi / 2.0f + (2.0f * kPi * i / segments);
        const int x = 160 + static_cast<int>(cosf(angle) * 88.0f);
        const int y = 124 + static_cast<int>(sinf(angle) * 88.0f);
        _display.fillCircle(x, y, i < lit ? 3 : 2, i < lit ? color : kBlue);
    }
}

void CountdownRenderer::copyKind(const char* kind) {
    const char* source = (kind != nullptr && *kind != '\0') ? kind : "TIMER";
    size_t i = 0;
    for (; source[i] != '\0' && i < sizeof(_kind) - 1; ++i) {
        char c = source[i];
        if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
        _kind[i] = c;
    }
    _kind[i] = '\0';
}

}  // namespace aura
