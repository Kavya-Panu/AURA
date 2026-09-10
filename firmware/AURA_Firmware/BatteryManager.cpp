// =============================================================================
//  hardware/BatteryManager.cpp
// -----------------------------------------------------------------------------
//  Reads the battery-sense ADC and converts to volts using the board's resistor
//  divider, then estimates a percentage against the configured LiPo range. All
//  tunables (pin, divider ratio, empty/full volts, poll interval) come from
//  Config. Sampling is periodic and non-blocking.
// =============================================================================
#include "BatteryManager.h"

namespace aura {

namespace {
constexpr uint8_t kUnsetPin = 0xFF;

inline float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
}  // namespace

void BatteryManager::begin() {
    _available = (cfg::hw::batteryHw::adcPin != kUnsetPin);
    if (!_available) {
        return;                       // safe "unknown" mode
    }
    analogReadResolution(12);         // 0..4095
    // 11 dB attenuation lets the ADC read the full divided range (~0..3.1 V).
    analogSetPinAttenuation(cfg::hw::batteryHw::adcPin, ADC_11db);

    _voltage = _prevVoltage = readVoltage();
    _percentage = estimatePercentage(_voltage);
    _sinceSampleMs = 0;
}

void BatteryManager::update(float dtMs) {
    if (!_available) {
        return;
    }
    if (dtMs < 0.0f) dtMs = 0.0f;
    _sinceSampleMs += static_cast<uint32_t>(dtMs);
    if (_sinceSampleMs < cfg::battery::pollMs) {
        return;
    }
    _sinceSampleMs = 0;

    _prevVoltage = _voltage;
    _voltage     = readVoltage();
    _percentage  = estimatePercentage(_voltage);

    // Best-effort charging estimate: no dedicated charge-status pin is exposed,
    // so infer it from a rising trend or a near-full terminal voltage.
    const bool rising = (_voltage - _prevVoltage) > 0.02f;
    _charging = rising || (_voltage >= cfg::hw::batteryHw::chargeVolts);
}

bool BatteryManager::isLowBattery() const {
    return _available && (_percentage <= cfg::battery::lowPercent);
}

BatteryManager::Status BatteryManager::status() const {
    return Status{_voltage, _percentage, _charging, isLowBattery(), _available};
}

// ---- private ----------------------------------------------------------------

float BatteryManager::readVoltage() const {
    // analogReadMilliVolts applies the ESP32's per-chip ADC calibration, giving
    // the millivolts at the pin; multiply back up through the divider ratio.
    const uint32_t pinMilliVolts =
        analogReadMilliVolts(cfg::hw::batteryHw::adcPin);
    return (static_cast<float>(pinMilliVolts) / 1000.0f) *
           cfg::hw::batteryHw::dividerRatio;
}

float BatteryManager::estimatePercentage(float volts) const {
    // Simple linear map across the configured LiPo range. (LiPo discharge is
    // non-linear; a curve can replace this later without touching callers.)
    const float lo = cfg::hw::batteryHw::emptyVolts;
    const float hi = cfg::hw::batteryHw::fullVolts;
    const float frac = clampf((volts - lo) / (hi - lo), 0.0f, 1.0f);
    return frac * 100.0f;
}

}  // namespace aura
