// =============================================================================
//  TouchManager.h
//  Low-traffic FT6336 gestures for the LCDWIKI ES3C28P touch screen.
// =============================================================================
#pragma once

#include <Arduino.h>

#include "Config.h"

namespace aura {

enum class TouchGesture : uint8_t { None, Tap, MultiTap, Swipe, LongPress };

struct TouchEvent {
    TouchGesture gesture = TouchGesture::None;
    uint16_t x = 0;
    uint16_t y = 0;
};

class TouchManager {
public:
    bool begin();
    TouchEvent update(uint32_t nowMs);
    bool isReady() const { return _ready; }

private:
    static void ARDUINO_ISR_ATTR onTouchInterrupt();
    static uint32_t distanceSquared(uint16_t x0, uint16_t y0,
                                    uint16_t x1, uint16_t y1);
    bool readPoint(bool& touched, uint16_t& x, uint16_t& y);

    static volatile bool _interruptPending;

    bool _ready = false;
    bool _pressed = false;
    bool _longPressSent = false;
    bool _pendingTap = false;
    bool _ignoreUntilRelease = false;

    uint32_t _lastReadMs = 0;
    uint32_t _pressStartedMs = 0;
    uint32_t _firstTapReleasedMs = 0;

    uint16_t _pressX = 0;
    uint16_t _pressY = 0;
    uint16_t _lastX = 0;
    uint16_t _lastY = 0;
    uint16_t _firstTapX = 0;
    uint16_t _firstTapY = 0;
    uint32_t _maxMovementSquared = 0;
};

}  // namespace aura
