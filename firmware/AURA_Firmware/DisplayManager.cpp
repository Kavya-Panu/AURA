// =============================================================================
// DisplayManager.cpp
// Full-frame buffered Adafruit ILI9341 backend.
// =============================================================================
#include "DisplayManager.h"

namespace aura {

namespace {
constexpr uint32_t kBacklightPwmFreq = 5000;
constexpr uint8_t  kBacklightPwmBits = 8;
}

DisplayManager::~DisplayManager() {
    delete _canvas;
    _canvas = nullptr;
}

bool DisplayManager::begin() {
    // Backlight is active HIGH on this board.
    pinMode(cfg::display::backlightPin, OUTPUT);
    digitalWrite(cfg::display::backlightPin, HIGH);
    delay(50);

    SPI.begin(
        cfg::display::spiClockPin,
        cfg::display::misoPin,
        cfg::display::mosiPin,
        cfg::display::chipSelectPin
    );

    _tft.begin(cfg::display::spiFrequency);
    _tft.setRotation(cfg::display::rotation);

    // This particular LCD panel uses inverted colour polarity. Enabling display
    // inversion restores the intended dark background and blue/cyan graphics.
    _tft.invertDisplay(cfg::display::invert);

    _width = _tft.width();
    _height = _tft.height();

    configureBacklight();
    setBrightness(cfg::backlight::defaultLevel);

    if (!allocateFrameBuffer()) {
        // Visible hardware-level indication if the RAM canvas cannot be created.
        _tft.fillScreen(ILI9341_RED);
        _tft.setCursor(10, 100);
        _tft.setTextColor(ILI9341_WHITE);
        _tft.setTextSize(2);
        _tft.print("FRAMEBUFFER ERROR");
        return false;
    }

    clear();
    _frameReady = true;
    presentFrame();

    _initialized = true;
    return true;
}

bool DisplayManager::allocateFrameBuffer() {
    delete _canvas;
    _canvas = new (std::nothrow) GFXcanvas16(
        static_cast<uint16_t>(_width),
        static_cast<uint16_t>(_height)
    );

    if (_canvas == nullptr || _canvas->getBuffer() == nullptr) {
        delete _canvas;
        _canvas = nullptr;
        return false;
    }

    _canvas->setRotation(0);
    _canvas->setTextWrap(false);
    return true;
}

void DisplayManager::update() {
    if (!_initialized || !_frameReady) {
        return;
    }

    presentFrame();
    _frameReady = false;
}

void DisplayManager::updateRegion(int x, int y, int w, int h) {
    if (!_initialized || _canvas == nullptr || _canvas->getBuffer() == nullptr) {
        return;
    }
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > _width) w = _width - x;
    if (y + h > _height) h = _height - y;
    if (w <= 0 || h <= 0) return;

    uint16_t* pixels = _canvas->getBuffer();
    _tft.startWrite();
    _tft.setAddrWindow(x, y, w, h);
    for (int row = 0; row < h; ++row) {
        _tft.writePixels(
            pixels + static_cast<uint32_t>(y + row) * _width + x,
            static_cast<uint32_t>(w),
            true,
            false
        );
    }
    _tft.endWrite();
}

void DisplayManager::presentFrame() {
    if (_canvas == nullptr || _canvas->getBuffer() == nullptr) {
        return;
    }

    // One address window and one SPI transaction for the complete frame.
    // The canvas stays entirely off-screen until this point, eliminating the
    // erase-then-redraw flicker seen with immediate-mode drawing.
    _tft.startWrite();
    _tft.setAddrWindow(0, 0, _width, _height);
    _tft.writePixels(
        _canvas->getBuffer(),
        static_cast<uint32_t>(_width) * static_cast<uint32_t>(_height),
        true,
        false
    );
    _tft.endWrite();
}

void DisplayManager::clear() {
    fillScreen(cfg::color::background);
}

void DisplayManager::fillScreen(uint16_t color) {
    if (_canvas != nullptr) {
        _canvas->fillScreen(color);
    }
}

void DisplayManager::setBrightness(uint8_t level) {
    if (level > cfg::backlight::max) {
        level = cfg::backlight::max;
    }

    _brightness = level;
    ledcWrite(cfg::display::backlightPin, level);
}

void DisplayManager::setRotation(uint8_t rotation) {
    // The framebuffer is fixed at landscape 320x240. Rotation 1 and 3 preserve
    // these dimensions; other rotations are deliberately ignored.
    if (rotation != 1 && rotation != 3) {
        return;
    }

    _tft.setRotation(rotation);
    _tft.invertDisplay(cfg::display::invert);
    _width = _tft.width();
    _height = _tft.height();
}

void DisplayManager::beginFrame() {
    // The canvas preserves the previous complete frame. Individual renderers
    // clear only their own drawing regions before drawing the new state.
}

void DisplayManager::endFrame() {
    _frameReady = true;
}

void DisplayManager::drawPixel(int x, int y, uint16_t color) {
    if (_canvas != nullptr) {
        _canvas->drawPixel(x, y, color);
    }
}

void DisplayManager::drawLine(int x0, int y0, int x1, int y1, uint16_t color) {
    if (_canvas != nullptr) {
        _canvas->drawLine(x0, y0, x1, y1, color);
    }
}

void DisplayManager::fillRect(int x, int y, int w, int h, uint16_t color) {
    if (_canvas != nullptr) {
        _canvas->fillRect(x, y, w, h, color);
    }
}

void DisplayManager::fillRoundRect(int x, int y, int w, int h, int radius,
                                   uint16_t color) {
    if (_canvas != nullptr) {
        _canvas->fillRoundRect(x, y, w, h, radius, color);
    }
}

void DisplayManager::fillCircle(int x, int y, int radius, uint16_t color) {
    if (_canvas != nullptr) {
        _canvas->fillCircle(x, y, radius, color);
    }
}

void DisplayManager::drawText(int x, int y, const char* text, uint16_t color,
                              uint8_t size) {
    if (_canvas == nullptr || text == nullptr) {
        return;
    }

    _canvas->setCursor(x, y);
    _canvas->setTextColor(color, cfg::color::background);
    _canvas->setTextSize(size);
    _canvas->print(text);
}

void DisplayManager::pushSprite(int x, int y, int w, int h,
                                const uint16_t* pixels) {
    if (_canvas == nullptr || pixels == nullptr || w <= 0 || h <= 0) {
        return;
    }

    _canvas->drawRGBBitmap(x, y, pixels, w, h);
}

void DisplayManager::configureBacklight() {
    ledcAttach(
        cfg::display::backlightPin,
        kBacklightPwmFreq,
        kBacklightPwmBits
    );
}

}  // namespace aura
