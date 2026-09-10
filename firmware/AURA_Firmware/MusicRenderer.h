// =============================================================================
// MusicRenderer.h
// Low-resolution procedural music visual for the 320x240 AURA display.
// No video is transported over USB; the ESP32 creates each frame locally from
// the current track metadata and a compact 0..100 audio-energy value.
// =============================================================================
#pragma once

#include <Arduino.h>

#include "Config.h"
#include "DisplayManager.h"

namespace aura {

class MusicRenderer {
public:
    explicit MusicRenderer(DisplayManager& display) : _display(display) {}

    void begin();
    void reset();
    void update(float dtMs);
    void render();

    void setMetadata(const char* title, const char* artist);
    void setPaused(bool paused) { _paused = paused; }
    void setLevel(uint8_t level) { _targetLevel = (level > 100) ? 100 : level; }

private:
    static uint16_t colorWheel(uint8_t position, uint8_t brightness);
    static void copyText(char* target, size_t capacity, const char* source);
    void drawPixelVideo();
    void drawTrackPanel();
    void drawEqualizer();

    DisplayManager& _display;
    char _title[44] = "Spotify";
    char _artist[36] = "AURA MUSIC";
    uint32_t _elapsedMs = 0;
    uint8_t _targetLevel = 0;
    uint8_t _level = 0;
    bool _paused = false;
};

}  // namespace aura
