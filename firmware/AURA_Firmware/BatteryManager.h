// =============================================================================
//  hardware/BatteryManager.h
// -----------------------------------------------------------------------------
//  Monitors battery voltage and estimates charge percentage. That is its whole
//  job: it reads the battery-sense ADC, converts through the board's voltage
//  divider, and reports status. It renders nothing, never touches serial, and
//  makes no robot-behaviour decisions — a leaf hardware module.
//
//  If the battery-sense pin is not configured (cfg::hw::batteryHw::adcPin ==
//  0xFF), the manager runs in a safe "unknown" mode: it reports zero volts, 0 %,
//  not-charging and not-low, so nothing downstream misbehaves.
//
//  Allowed dependencies: Arduino.h, Config.h.
// =============================================================================
#pragma once

#include <Arduino.h>

#include "Config.h"

namespace aura {

class BatteryManager {
public:
    /// Snapshot of battery state.
    struct Status {
        float voltage;      ///< battery volts (0 if unavailable)
        float percentage;   ///< 0..100 (0 if unavailable)
        bool  charging;     ///< best-effort estimate (no dedicated sense pin)
        bool  low;          ///< at/below the low-battery threshold
        bool  available;    ///< false when the sense pin is unconfigured
    };

    BatteryManager() = default;

    /// Configure the ADC. Safe to call even when the sense pin is unset.
    void begin();

    /// Sample periodically (every cfg::battery::pollMs). Non-blocking.
    void update(float dtMs);

    float voltage() const { return _voltage; }        ///< last battery volts
    float percentage() const { return _percentage; }  ///< last estimate 0..100
    bool  isCharging() const { return _charging; }
    bool  isLowBattery() const;
    Status status() const;

private:
    float readVoltage() const;
    float estimatePercentage(float volts) const;

    bool     _available    = false;
    float    _voltage      = 0.0f;
    float    _percentage   = 0.0f;
    float    _prevVoltage  = 0.0f;
    bool     _charging     = false;
    uint32_t _sinceSampleMs = 0;
};

}  // namespace aura
