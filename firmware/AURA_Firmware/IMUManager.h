// =============================================================================
//  hardware/IMUManager.h
// -----------------------------------------------------------------------------
//  Reads the onboard QMI8658 6-axis IMU (accelerometer + gyroscope) over I2C and
//  derives orientation and a movement flag. That is its whole job: it produces
//  sensor data. It never controls the robot, renders anything, or touches
//  serial — a leaf hardware module. Higher layers decide what motion means.
//
//  Self-contained register-level driver (via Wire), so it pulls in no external
//  sensor library.
//
//  Allowed dependencies: Arduino.h, Wire.h, Config.h.
// =============================================================================
#pragma once

#include <Arduino.h>
#include <Wire.h>

#include "Config.h"

namespace aura {

/// A simple 3-component vector (units depend on the accessor: g or deg/s).
struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

class IMUManager {
public:
    /// Board tilt derived from gravity, in degrees.
    struct Orientation {
        float pitch = 0.0f;
        float roll  = 0.0f;
    };

    IMUManager() = default;

    /// Initialise I2C and the QMI8658. Returns false if the device is not found
    /// (WHO_AM_I mismatch) so callers can report the failure.
    bool begin();

    /// Read a fresh sample. Non-blocking; call once per frame.
    void update(float dtMs);

    Vec3 acceleration() const { return _accel; }   ///< g
    Vec3 gyroscope()    const { return _gyro; }     ///< deg/s (bias-corrected)
    Orientation orientation() const { return _orientation; }
    bool isMoving() const { return _moving; }

    /// Sample the gyroscope at rest to capture its zero-rate bias. Keep the
    /// board still while calling. Returns false if not initialised.
    bool calibrate();

    bool isReady() const { return _ready; }

private:
    bool    writeReg(uint8_t reg, uint8_t value);
    bool    readRegs(uint8_t reg, uint8_t* buf, size_t len);
    int16_t readAxis(const uint8_t* p) const;      ///< little-endian int16

    Vec3        _accel;
    Vec3        _gyro;
    Vec3        _gyroBias;
    Orientation _orientation;
    bool        _moving = false;
    bool        _ready  = false;
};

}  // namespace aura
