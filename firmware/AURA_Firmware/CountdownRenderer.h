// =============================================================================
// CountdownRenderer.h - animated timer/alarm/reminder scene for AURA
// =============================================================================
#pragma once

#include <Arduino.h>
#include "DisplayManager.h"

namespace aura {

class CountdownRenderer {
public:
    explicit CountdownRenderer(DisplayManager& display) : _display(display) {}

    void begin() { stop(); }
    void start(uint32_t seconds, const char* kind);
    void alert(const char* kind);
    void stop();
    void render();

    bool active() const { return _mode != Mode::Hidden; }
    bool alerting() const { return _mode == Mode::Alert; }
    uint32_t remainingSeconds() const;

private:
    enum class Mode : uint8_t { Hidden, Countdown, Alert };

    void drawCountdown(uint32_t remaining);
    void drawAlert();
    void drawProgressRing(float ratio, uint16_t color);
    void copyKind(const char* kind);

    DisplayManager& _display;
    Mode _mode = Mode::Hidden;
    uint32_t _durationSeconds = 0;
    uint32_t _startedAtMs = 0;
    char _kind[12] = "TIMER";
};

}  // namespace aura
