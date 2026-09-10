#pragma once

#include <Arduino.h>

namespace aura {

// Controls the small top DC motor through channel A of a DRV8833 H-bridge.
// SLP is held low during startup/stopping and both motor inputs use PWM so
// direction and speed can be controlled without changing the wiring.
class TopMotorController {
public:
    // DC motor feature retired at the user's request. Rebuilding is required
    // to enable it again; serial commands cannot override this setting.
    static constexpr bool kEnabled = false;
    bool begin();
    void update(uint32_t nowMs);

    void startTest();
    void runPulse(uint8_t percent, uint32_t holdMs);
    void runPattern(uint8_t percent, uint32_t holdMs, uint8_t pulses,
                    uint32_t gapMs = 250);
    void setForward(uint8_t percent);
    void setReverse(uint8_t percent);
    void stop();

    bool ready() const { return _ready; }
    bool running() const { return _currentPercent > 0; }
    bool testRunning() const { return _testPhase != TestPhase::Idle; }
    uint8_t speedPercent() const { return _currentPercent; }
    bool consumeTestCompleted();

private:
    enum class Direction : uint8_t { Stopped, Forward, Reverse };
    enum class TestPhase : uint8_t { Idle, RampUp, Hold, RampDown, Gap };

    static constexpr uint8_t kSleepPin = 14;   // DRV8833 SLP (active high)
    static constexpr uint8_t kInput1Pin = 2;   // DRV8833 IN1
    static constexpr uint8_t kInput2Pin = 3;   // DRV8833 IN2
    static constexpr uint32_t kPwmFrequencyHz = 15000;
    static constexpr uint8_t kPwmResolutionBits = 8;
    static constexpr uint8_t kMaximumPercent = 80;
    static constexpr uint8_t kTestPercent = 75;
    static constexpr uint32_t kRampIntervalMs = 20;
    static constexpr uint32_t kTestHoldMs = 1200;

    void setDirection(Direction direction);
    void setTarget(uint8_t percent, Direction direction);
    void writePercent(uint8_t percent);

    Direction _direction = Direction::Stopped;
    uint8_t _currentPercent = 0;
    uint8_t _targetPercent = 0;
    uint32_t _lastRampMs = 0;
    uint32_t _testHoldStartedMs = 0;
    uint32_t _holdDurationMs = kTestHoldMs;
    TestPhase _testPhase = TestPhase::Idle;
    bool _reportTestCompletion = false;
    bool _testCompleted = false;
    bool _ready = false;
    uint8_t _pulsesRemaining = 0;
    uint8_t _patternPercent = 0;
    uint32_t _patternGapMs = 250;
    uint32_t _gapStartedMs = 0;
};

}  // namespace aura
