// =============================================================================
// DisplayManager.h
// Flicker-free display backend for the LCDWIKI ES3C28P ESP32-S3 board.
//
// The complete 320x240 frame is drawn into a 16-bit RAM canvas and transferred
// to the ILI9341 in one SPI transaction. Other modules never access the LCD
// driver directly.
// =============================================================================
#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <new>

#include "Config.h"
#include "Constants.h"

namespace aura {

class DisplayManager {
public:
    DisplayManager() = default;
    ~DisplayManager();

    DisplayManager(const DisplayManager&) = delete;
    DisplayManager& operator=(const DisplayManager&) = delete;

    bool begin();
    void update();
    /// Present only part of the framebuffer (used for low-bandwidth gaze
    /// updates while microphone audio is streaming).
    void updateRegion(int x, int y, int w, int h);

    void clear();
    void fillScreen(uint16_t color);
    void setBrightness(uint8_t level);
    void setRotation(uint8_t rotation);

    int width() const { return _width; }
    int height() const { return _height; }
    uint8_t brightness() const { return _brightness; }

    void beginFrame();
    void endFrame();

    void drawPixel(int x, int y, uint16_t color);
    void drawLine(int x0, int y0, int x1, int y1, uint16_t color);
    void fillRect(int x, int y, int w, int h, uint16_t color);
    void fillRoundRect(int x, int y, int w, int h, int radius, uint16_t color);
    void fillCircle(int x, int y, int radius, uint16_t color);

    void drawText(int x, int y, const char* text, uint16_t color,
                  uint8_t size = 1);

    void pushSprite(int x, int y, int w, int h, const uint16_t* pixels);

private:
    void configureBacklight();
    bool allocateFrameBuffer();
    void presentFrame();

    Adafruit_ILI9341 _tft{
        &SPI,
        cfg::display::dataCommandPin,
        cfg::display::chipSelectPin,
        cfg::display::resetPin
    };

    GFXcanvas16* _canvas = nullptr;

    int _width = 0;
    int _height = 0;
    uint8_t _brightness = cfg::backlight::defaultLevel;
    bool _initialized = false;
    bool _frameReady = false;
};

}  // namespace aura
