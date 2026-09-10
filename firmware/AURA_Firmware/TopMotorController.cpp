#include "TopMotorController.h"

namespace aura {

bool TopMotorController::begin() {
    // Keep the bridge asleep until both PWM inputs are configured and low.
    pinMode(kSleepPin, OUTPUT);
    digitalWrite(kSleepPin, LOW);

    if (!kEnabled) {
        pinMode(kInput1Pin, OUTPUT);
        pinMode(kInput2Pin, OUTPUT);
        digitalWrite(kInput1Pin, LOW);
        digitalWrite(kInput2Pin, LOW);
        _ready = false;
        return false;
    }

    if (!ledcAttach(kInput1Pin, kPwmFrequencyHz, kPwmResolutionBits)) {
        _ready = false;
        return false;
    }
    if (!ledcAttach(kInput2Pin, kPwmFrequencyHz, kPwmResolutionBits)) {
        ledcDetach(kInput1Pin);
        _ready = false;
        return false;
    }

    ledcWrite(kInput1Pin, 0);
    ledcWrite(kInput2Pin, 0);
    _direction = Direction::Stopped;
    _currentPercent = 0;
    _targetPercent = 0;
    _lastRampMs = millis();
    _testPhase = TestPhase::Idle;
    _testCompleted = false;
    _ready = true;
    return true;
}

void TopMotorController::setDirection(Direction direction) {
    _direction = direction;
    if (direction == Direction::Stopped) {
        ledcWrite(kInput1Pin, 0);
        ledcWrite(kInput2Pin, 0);
        digitalWrite(kSleepPin, LOW);
    } else {
        digitalWrite(kSleepPin, HIGH);
    }
}

void TopMotorController::writePercent(uint8_t percent) {
    if (percent > 100) percent = 100;
    const uint32_t duty = (static_cast<uint32_t>(percent) * 255U) / 100U;
    switch (_direction) {
        case Direction::Forward:
            ledcWrite(kInput1Pin, duty);
            ledcWrite(kInput2Pin, 0);
            break;
        case Direction::Reverse:
            ledcWrite(kInput1Pin, 0);
            ledcWrite(kInput2Pin, duty);
            break;
        case Direction::Stopped:
            ledcWrite(kInput1Pin, 0);
            ledcWrite(kInput2Pin, 0);
            break;
    }
}

void TopMotorController::setTarget(uint8_t percent, Direction direction) {
    if (!_ready) return;
    if (percent > kMaximumPercent) percent = kMaximumPercent;

    // Never reverse an energized motor. Ramp to zero first; callers can issue
    // the opposite-direction command again once stopped.
    if (_currentPercent > 0 && direction != _direction) {
        _targetPercent = 0;
        return;
    }

    if (_currentPercent == 0) setDirection(direction);
    _targetPercent = percent;
    _testPhase = TestPhase::Idle;
    _pulsesRemaining = 0;
}

void TopMotorController::setForward(uint8_t percent) {
    setTarget(percent, Direction::Forward);
}

void TopMotorController::setReverse(uint8_t percent) {
    setTarget(percent, Direction::Reverse);
}

void TopMotorController::stop() {
    if (!_ready) return;
    _targetPercent = 0;
    _currentPercent = 0;
    writePercent(0);
    setDirection(Direction::Stopped);
    _testPhase = TestPhase::Idle;
    _reportTestCompletion = false;
    _pulsesRemaining = 0;
}

void TopMotorController::startTest() {
    if (!_ready) return;
    stop();
    setDirection(Direction::Forward);
    _targetPercent = kTestPercent;
    _holdDurationMs = kTestHoldMs;
    _testPhase = TestPhase::RampUp;
    _reportTestCompletion = true;
    _testCompleted = false;
    _lastRampMs = millis();
}

void TopMotorController::runPulse(uint8_t percent, uint32_t holdMs) {
    runPattern(percent, holdMs, 1);
}

void TopMotorController::runPattern(uint8_t percent, uint32_t holdMs,
                                    uint8_t pulses, uint32_t gapMs) {
    if (!_ready) return;
    if (percent > kMaximumPercent) percent = kMaximumPercent;
    if (percent == 0 || holdMs == 0 || pulses == 0) {
        stop();
        return;
    }

    stop();
    setDirection(Direction::Forward);
    _targetPercent = percent;
    _patternPercent = percent;
    _pulsesRemaining = min<uint8_t>(pulses, 3) - 1;
    _patternGapMs = min(gapMs, 1000UL);
    _holdDurationMs = min(holdMs, 4000UL);
    _testPhase = TestPhase::RampUp;
    _reportTestCompletion = false;
    _testCompleted = false;
    _lastRampMs = millis();
}

void TopMotorController::update(uint32_t nowMs) {
    if (!_ready) return;

    if (nowMs - _lastRampMs >= kRampIntervalMs) {
        // Account for time spent rendering the screen, not just loop count.
        // Limit each adjustment to 10% even after a long stall.
        const uint32_t intervals = (nowMs - _lastRampMs) / kRampIntervalMs;
        const uint8_t step = static_cast<uint8_t>(min<uint32_t>(intervals, 5) * 2);
        _lastRampMs += intervals * kRampIntervalMs;
        if (_currentPercent < _targetPercent) {
            const uint8_t remaining = _targetPercent - _currentPercent;
            _currentPercent += min<uint8_t>(step, remaining);
            writePercent(_currentPercent);
        } else if (_currentPercent > _targetPercent) {
            const uint8_t remaining = _currentPercent - _targetPercent;
            _currentPercent -= min<uint8_t>(step, remaining);
            writePercent(_currentPercent);
            if (_currentPercent == 0) setDirection(Direction::Stopped);
        }
    }

    switch (_testPhase) {
        case TestPhase::RampUp:
            if (_currentPercent >= _targetPercent) {
                _testHoldStartedMs = nowMs;
                _testPhase = TestPhase::Hold;
            }
            break;
        case TestPhase::Hold:
            if (nowMs - _testHoldStartedMs >= _holdDurationMs) {
                _targetPercent = 0;
                _testPhase = TestPhase::RampDown;
            }
            break;
        case TestPhase::RampDown:
            if (_currentPercent == 0) {
                setDirection(Direction::Stopped);
                if (_pulsesRemaining > 0) {
                    --_pulsesRemaining;
                    _gapStartedMs = nowMs;
                    _testPhase = TestPhase::Gap;
                } else {
                    _testPhase = TestPhase::Idle;
                    if (_reportTestCompletion) _testCompleted = true;
                    _reportTestCompletion = false;
                }
            }
            break;
        case TestPhase::Gap:
            if (nowMs - _gapStartedMs >= _patternGapMs) {
                setDirection(Direction::Forward);
                _targetPercent = _patternPercent;
                _testPhase = TestPhase::RampUp;
            }
            break;
        case TestPhase::Idle:
            break;
    }
}

bool TopMotorController::consumeTestCompleted() {
    const bool completed = _testCompleted;
    _testCompleted = false;
    return completed;
}

}  // namespace aura
