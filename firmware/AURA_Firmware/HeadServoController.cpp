#include "HeadServoController.h"

#include <math.h>

namespace aura {

bool HeadServoController::begin() {
    _servo.setPeriodHertz(50);
    const int channel = _servo.attach(kPin, 500, 2400);
    if (channel < 0) {
        _ready = false;
        return false;
    }

    _currentDeg = kCenterDeg;
    _targetDeg = kCenterDeg;
    _velocityDegPerSecond = 0.0f;
    _servo.write(static_cast<int>(kCenterDeg));
    _lastUpdateMs = millis();
    _ready = true;
    return true;
}

void HeadServoController::setTarget(float angleDeg) {
    if (angleDeg < kMinDeg) angleDeg = kMinDeg;
    if (angleDeg > kMaxDeg) angleDeg = kMaxDeg;
    _targetDeg = angleDeg;
}

void HeadServoController::update(uint32_t nowMs) {
    if (!_ready) return;

    const uint32_t elapsedMs = nowMs - _lastUpdateMs;
    if (elapsedMs < kUpdateIntervalMs) return;
    _lastUpdateMs = nowMs;

    const float dt = min(elapsedMs / 1000.0f, 0.10f);
    const float delta = _targetDeg - _currentDeg;

    // Acceleration-limited motion with a calculated braking speed. This avoids
    // the sharp starts, stops and direction changes caused by noisy camera
    // targets while still allowing the head to catch up naturally.
    float desiredVelocity = 0.0f;
    if (fabsf(delta) > 0.20f) {
        const float brakingSpeed = sqrtf(
            2.0f * kAccelerationDegPerSecond2 * fabsf(delta)
        );
        const float speed = min(kMaxSpeedDegPerSecond, brakingSpeed);
        desiredVelocity = delta > 0.0f ? speed : -speed;
    }

    const float maxVelocityChange = kAccelerationDegPerSecond2 * dt;
    const float velocityError = desiredVelocity - _velocityDegPerSecond;
    if (velocityError > maxVelocityChange) {
        _velocityDegPerSecond += maxVelocityChange;
    } else if (velocityError < -maxVelocityChange) {
        _velocityDegPerSecond -= maxVelocityChange;
    } else {
        _velocityDegPerSecond = desiredVelocity;
    }

    const float next = _currentDeg + _velocityDegPerSecond * dt;
    const bool wouldPassTarget =
        (delta > 0.0f && next >= _targetDeg)
        || (delta < 0.0f && next <= _targetDeg);
    if (wouldPassTarget || (fabsf(delta) <= 0.20f
            && fabsf(_velocityDegPerSecond) < 1.0f)) {
        _currentDeg = _targetDeg;
        _velocityDegPerSecond = 0.0f;
    } else {
        _currentDeg = next;
    }

    _servo.write(static_cast<int>(lroundf(_currentDeg)));
}

}  // namespace aura
