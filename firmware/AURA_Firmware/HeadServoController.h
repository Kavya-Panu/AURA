#pragma once

#include <Arduino.h>
#include <ESP32Servo.h>

namespace aura {

class HeadServoController {
public:
    bool begin();
    void setTarget(float angleDeg);
    void update(uint32_t nowMs);

    float currentAngle() const { return _currentDeg; }
    float targetAngle() const { return _targetDeg; }

private:
    static constexpr int kPin = 21;
    static constexpr float kMinDeg = 5.0f;
    static constexpr float kMaxDeg = 175.0f;
    static constexpr float kCenterDeg = 95.0f;
    static constexpr float kMaxSpeedDegPerSecond = 55.0f;
    static constexpr float kAccelerationDegPerSecond2 = 140.0f;
    static constexpr uint32_t kUpdateIntervalMs = 20;

    Servo _servo;
    float _currentDeg = kCenterDeg;
    float _targetDeg = kCenterDeg;
    float _velocityDegPerSecond = 0.0f;
    uint32_t _lastUpdateMs = 0;
    bool _ready = false;
};

}  // namespace aura
