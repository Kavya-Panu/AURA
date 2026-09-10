// =============================================================================
//  TouchManager.cpp
//  Uses the existing shared Wire bus. It never calls Wire.begin(), so the
//  working ES8311 microphone/speaker configuration remains untouched.
// =============================================================================
#include "TouchManager.h"

#include <Wire.h>

namespace aura {

volatile bool TouchManager::_interruptPending = false;

namespace {
constexpr uint8_t kTouchStatusRegister = 0x02;

TouchEvent noEvent() {
    return {};
}
}  // namespace

void ARDUINO_ISR_ATTR TouchManager::onTouchInterrupt() {
    _interruptPending = true;
}

bool TouchManager::begin() {
    if (!cfg::hw::touch::present) return false;

    pinMode(cfg::hw::touch::pinInt, INPUT);
    pinMode(cfg::hw::touch::pinRst, OUTPUT);
    digitalWrite(cfg::hw::touch::pinRst, LOW);
    delay(20);
    digitalWrite(cfg::hw::touch::pinRst, HIGH);
    delay(180);

    // Wire is already configured by AudioManager on these same SDA/SCL pins.
    // A short timeout prevents a faulty touch transaction from freezing AURA.
    Wire.setTimeOut(cfg::hw::touch::wireTimeoutMs);
    Wire.beginTransmission(cfg::hw::touch::i2cAddress);
    _ready = (Wire.endTransmission() == 0);
    if (!_ready) return false;

    _interruptPending = false;
    attachInterrupt(digitalPinToInterrupt(cfg::hw::touch::pinInt),
                    onTouchInterrupt, FALLING);
    _lastReadMs = millis();
    return true;
}

uint32_t TouchManager::distanceSquared(uint16_t x0, uint16_t y0,
                                       uint16_t x1, uint16_t y1) {
    const int32_t dx = static_cast<int32_t>(x1) - static_cast<int32_t>(x0);
    const int32_t dy = static_cast<int32_t>(y1) - static_cast<int32_t>(y0);
    return static_cast<uint32_t>(dx * dx + dy * dy);
}

bool TouchManager::readPoint(bool& touched, uint16_t& x, uint16_t& y) {
    Wire.beginTransmission(cfg::hw::touch::i2cAddress);
    Wire.write(kTouchStatusRegister);
    if (Wire.endTransmission() != 0) return false;

    const uint8_t received = Wire.requestFrom(
        cfg::hw::touch::i2cAddress, static_cast<uint8_t>(5));
    if (received != 5) {
        while (Wire.available()) Wire.read();
        return false;
    }

    const uint8_t count = static_cast<uint8_t>(Wire.read()) & 0x0F;
    const uint8_t xHigh = static_cast<uint8_t>(Wire.read());
    const uint8_t xLow  = static_cast<uint8_t>(Wire.read());
    const uint8_t yHigh = static_cast<uint8_t>(Wire.read());
    const uint8_t yLow  = static_cast<uint8_t>(Wire.read());

    touched = (count > 0 && count < 3);
    if (!touched) return true;

    const uint16_t rawX = static_cast<uint16_t>(((xHigh & 0x0F) << 8) | xLow);
    const uint16_t rawY = static_cast<uint16_t>(((yHigh & 0x0F) << 8) | yLow);

    // Display rotation 1: native portrait touch coordinates -> landscape.
    x = static_cast<uint16_t>(constrain(
        static_cast<int>(rawY), 0, cfg::display::width - 1));
    y = static_cast<uint16_t>(constrain(
        static_cast<int>(cfg::hw::touch::rawWidth - rawX),
        0, cfg::display::height - 1));
    return true;
}

TouchEvent TouchManager::update(uint32_t nowMs) {
    if (!_ready) return noEvent();

    if (_pendingTap && !_pressed
            && (nowMs - _firstTapReleasedMs) > cfg::hw::touch::multiTapGapMs) {
        _pendingTap = false;
        return {TouchGesture::Tap, _firstTapX, _firstTapY};
    }

    const bool interruptSeen = _interruptPending;
    if (interruptSeen) _interruptPending = false;

    const uint16_t interval = _pressed
        ? cfg::hw::touch::pressedPollMs
        : cfg::hw::touch::idleSafetyPollMs;
    if (!interruptSeen && (nowMs - _lastReadMs) < interval) return noEvent();
    _lastReadMs = nowMs;

    bool touched = false;
    uint16_t x = _lastX;
    uint16_t y = _lastY;
    if (!readPoint(touched, x, y)) return noEvent();

    if (_ignoreUntilRelease) {
        if (!touched) _ignoreUntilRelease = false;
        return noEvent();
    }

    if (touched) {
        if (!_pressed) {
            _pressed = true;
            _longPressSent = false;
            _pressStartedMs = nowMs;
            _pressX = _lastX = x;
            _pressY = _lastY = y;
            _maxMovementSquared = 0;
        } else {
            _lastX = x;
            _lastY = y;
            const uint32_t movement = distanceSquared(_pressX, _pressY, x, y);
            if (movement > _maxMovementSquared) _maxMovementSquared = movement;
        }

        const uint32_t toleranceSq =
            cfg::hw::touch::stationaryTolerancePx
            * cfg::hw::touch::stationaryTolerancePx;
        if (!_longPressSent
                && (nowMs - _pressStartedMs) >= cfg::hw::touch::longPressMs
                && _maxMovementSquared <= toleranceSq) {
            _longPressSent = true;
            _pendingTap = false;
            return {TouchGesture::LongPress, _lastX, _lastY};
        }
        return noEvent();
    }

    if (!_pressed) return noEvent();
    _pressed = false;
    if (_longPressSent) return noEvent();

    const uint32_t heldMs = nowMs - _pressStartedMs;
    const uint32_t swipeSq =
        cfg::hw::touch::swipeMinDistancePx
        * cfg::hw::touch::swipeMinDistancePx;
    if (heldMs <= cfg::hw::touch::swipeMaxMs
            && _maxMovementSquared >= swipeSq) {
        _pendingTap = false;
        return {TouchGesture::Swipe, _lastX, _lastY};
    }

    const uint32_t toleranceSq =
        cfg::hw::touch::stationaryTolerancePx
        * cfg::hw::touch::stationaryTolerancePx;
    if (heldMs > cfg::hw::touch::tapMaxMs || _maxMovementSquared > toleranceSq) {
        return noEvent();
    }

    if (_pendingTap
            && (nowMs - _firstTapReleasedMs) <= cfg::hw::touch::multiTapGapMs
            && distanceSquared(_firstTapX, _firstTapY, _lastX, _lastY)
                <= cfg::hw::touch::multiTapDistancePx
                   * cfg::hw::touch::multiTapDistancePx) {
        _pendingTap = false;
        _ignoreUntilRelease = true;
        return {TouchGesture::MultiTap, _lastX, _lastY};
    }

    _pendingTap = true;
    _firstTapReleasedMs = nowMs;
    _firstTapX = _lastX;
    _firstTapY = _lastY;
    return noEvent();
}

}  // namespace aura
