// =============================================================================
//  hardware/IMUManager.cpp
// -----------------------------------------------------------------------------
//  Minimal QMI8658 driver. Configures the accelerometer (±4 g) and gyroscope
//  (±512 deg/s) over I2C, reads the six 16-bit axes, converts to physical units,
//  and derives pitch/roll plus a movement flag. Register addresses and the
//  configuration values follow the QMI8658 datasheet; the exact ODR/scale bits
//  are named constants and should be confirmed on hardware.
// =============================================================================
#include "IMUManager.h"

namespace aura {

namespace {
// ---- QMI8658 register map (subset) -----------------------------------------
constexpr uint8_t REG_WHO_AM_I = 0x00;
constexpr uint8_t REG_CTRL1    = 0x02;   // serial interface / auto-increment
constexpr uint8_t REG_CTRL2    = 0x03;   // accelerometer settings
constexpr uint8_t REG_CTRL3    = 0x04;   // gyroscope settings
constexpr uint8_t REG_CTRL7    = 0x08;   // enable accel / gyro
constexpr uint8_t REG_AX_L     = 0x35;   // accel X..Z, then gyro X..Z, LE int16
constexpr uint8_t WHO_AM_I_VAL = 0x05;

// Configuration values (see datasheet). Kept named for on-device tuning.
constexpr uint8_t CTRL1_AUTOINC = 0x40;  // address auto-increment on burst read
constexpr uint8_t CTRL2_ACC_4G_ODR = 0x03 | 0x30;  // ±4 g, mid ODR
constexpr uint8_t CTRL3_GYR_512_ODR = 0x50 | 0x03;  // ±512 dps, mid ODR
constexpr uint8_t CTRL7_ENABLE_AG  = 0x03;          // aEN | gEN

// Sensitivities matching the ranges above.
constexpr float ACC_LSB_PER_G   = 8192.0f;   // 32768 / 4 g
constexpr float GYR_LSB_PER_DPS = 64.0f;     // 32768 / 512 dps

// Movement thresholds.
constexpr float MOVE_ACC_G   = 0.08f;    // |‖a‖ - 1g| beyond this = moving
constexpr float MOVE_GYR_DPS = 8.0f;     // gyro magnitude beyond this = moving

constexpr int   CALIBRATE_SAMPLES = 64;

inline float magnitude(const Vec3& v) {
    return sqrtf(v.x * v.x + v.y * v.y + v.z * v.z);
}
}  // namespace

bool IMUManager::begin() {
    if (!cfg::hw::imu::present) {
        _ready = false;                 // board has no IMU: stay idle, touch no bus
        return false;
    }

    Wire.begin(cfg::hw::imu::pinSda, cfg::hw::imu::pinScl);
    Wire.setClock(cfg::hw::imu::i2cClockHz);

    uint8_t who = 0;
    if (!readRegs(REG_WHO_AM_I, &who, 1) || who != WHO_AM_I_VAL) {
        _ready = false;
        return false;                   // device absent / wrong address
    }

    writeReg(REG_CTRL1, CTRL1_AUTOINC);
    writeReg(REG_CTRL2, CTRL2_ACC_4G_ODR);
    writeReg(REG_CTRL3, CTRL3_GYR_512_ODR);
    writeReg(REG_CTRL7, CTRL7_ENABLE_AG);

    _ready = true;
    return true;
}

void IMUManager::update(float /*dtMs*/) {
    if (!_ready) {
        return;
    }

    uint8_t raw[12];
    if (!readRegs(REG_AX_L, raw, sizeof(raw))) {
        return;                         // transient bus error: keep last sample
    }

    _accel.x = readAxis(&raw[0]) / ACC_LSB_PER_G;
    _accel.y = readAxis(&raw[2]) / ACC_LSB_PER_G;
    _accel.z = readAxis(&raw[4]) / ACC_LSB_PER_G;

    _gyro.x = readAxis(&raw[6])  / GYR_LSB_PER_DPS - _gyroBias.x;
    _gyro.y = readAxis(&raw[8])  / GYR_LSB_PER_DPS - _gyroBias.y;
    _gyro.z = readAxis(&raw[10]) / GYR_LSB_PER_DPS - _gyroBias.z;

    // Orientation from gravity (degrees).
    _orientation.pitch =
        atan2f(-_accel.x, sqrtf(_accel.y * _accel.y + _accel.z * _accel.z)) *
        57.29578f;
    _orientation.roll = atan2f(_accel.y, _accel.z) * 57.29578f;

    // Movement: acceleration magnitude departing from 1 g, or rotating.
    const float accDev = fabsf(magnitude(_accel) - 1.0f);
    _moving = (accDev > MOVE_ACC_G) || (magnitude(_gyro) > MOVE_GYR_DPS);
}

bool IMUManager::calibrate() {
    if (!_ready) {
        return false;
    }
    Vec3 sum;
    int taken = 0;
    for (int i = 0; i < CALIBRATE_SAMPLES; ++i) {
        uint8_t raw[12];
        if (!readRegs(REG_AX_L, raw, sizeof(raw))) {
            continue;
        }
        sum.x += readAxis(&raw[6])  / GYR_LSB_PER_DPS;
        sum.y += readAxis(&raw[8])  / GYR_LSB_PER_DPS;
        sum.z += readAxis(&raw[10]) / GYR_LSB_PER_DPS;
        ++taken;
        delay(2);
    }
    if (taken == 0) {
        return false;
    }
    _gyroBias.x = sum.x / taken;
    _gyroBias.y = sum.y / taken;
    _gyroBias.z = sum.z / taken;
    return true;
}

// ---- private ----------------------------------------------------------------

bool IMUManager::writeReg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(cfg::hw::imu::i2cAddress);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

bool IMUManager::readRegs(uint8_t reg, uint8_t* buf, size_t len) {
    Wire.beginTransmission(cfg::hw::imu::i2cAddress);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) {          // repeated start
        return false;
    }
    const size_t got = Wire.requestFrom(
        static_cast<int>(cfg::hw::imu::i2cAddress), static_cast<int>(len));
    if (got != len) {
        return false;
    }
    for (size_t i = 0; i < len; ++i) {
        buf[i] = static_cast<uint8_t>(Wire.read());
    }
    return true;
}

int16_t IMUManager::readAxis(const uint8_t* p) const {
    return static_cast<int16_t>(static_cast<uint16_t>(p[0]) |
                                (static_cast<uint16_t>(p[1]) << 8));
}

}  // namespace aura
