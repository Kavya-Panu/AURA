// =============================================================================
//  core/Config.h
// -----------------------------------------------------------------------------
//  Every TUNABLE value for the AURA face firmware, in one place.
//
//  Rule: no module hard-codes geometry, colours, pins or timing. If a value
//  might reasonably be adjusted while tuning the robot's look or feel, it lives
//  here as a `constexpr` inside a logical namespace. Values that are FIXED by
//  the firmware/protocol specification (baud rate, command tokens, version)
//  live in core/Constants.h instead.
//
//  This header contains data only — no classes, no functions with side effects.
//  The one helper is a constexpr colour packer, which is pure and compile-time.
// =============================================================================
#pragma once

#include <cstdint>

namespace aura {
namespace cfg {

// -----------------------------------------------------------------------------
//  Colour helper: pack 8-bit R,G,B into a 16-bit RGB565 value at compile time.
//  Pure and constexpr — safe to use in the colour constants below.
// -----------------------------------------------------------------------------
constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
    return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// -----------------------------------------------------------------------------
//  Board profile selection
//  The active board is chosen by a -DBOARD_* build flag in platformio.ini.
//  If none is supplied, fall back to the LCDWIKI ES3C28P ILI9341 board used
//  by this Arduino IDE project.
// -----------------------------------------------------------------------------
#if !defined(BOARD_ILI9341_240x320) && \
    !defined(BOARD_S3_ST7796) && \
    !defined(BOARD_S3_WAVESHARE_ST7789) && \
    !defined(BOARD_S3_LCDWIKI_ILI9341)
  #define BOARD_S3_LCDWIKI_ILI9341
#endif

// -----------------------------------------------------------------------------
//  Display: panel geometry, orientation and backlight pin (board-dependent).
// -----------------------------------------------------------------------------
namespace display {

#if defined(BOARD_S3_ST7796)
    constexpr int      width          = 480;
    constexpr int      height         = 320;
    constexpr uint8_t  rotation       = 1;      // landscape (TFT_eSPI index)
    constexpr bool     invert         = true;
    constexpr uint8_t  backlightPin   = 14;
#elif defined(BOARD_S3_WAVESHARE_ST7789)
    // Waveshare ESP32-S3-Touch-LCD-2.8 (ST7789 240x320 IPS) — production board.
    constexpr int      width          = 320;    // landscape (native panel 240x320)
    constexpr int      height         = 240;
    constexpr uint8_t  rotation       = 1;      // try 3 if the image is upside-down
    constexpr bool     invert         = true;   // ST7789 IPS panels need inversion ON
    constexpr uint8_t  backlightPin   = 5;      // LCD_BL = GPIO5 (Waveshare wiki)
#elif defined(BOARD_S3_LCDWIKI_ILI9341)
    // LCDWIKI 2.8" ESP32-S3 (ES3C28P), ILI9341V 240x320.
    constexpr int      width          = 320;
    constexpr int      height         = 240;
    constexpr uint8_t  rotation       = 1;

    // Required by this physical panel. Without inversion, black appears white
    // and cyan/blue appears red/orange.
    constexpr bool     invert         = true;

    constexpr int8_t   chipSelectPin  = 10;
    constexpr int8_t   dataCommandPin = 46;
    constexpr int8_t   spiClockPin    = 12;
    constexpr int8_t   mosiPin        = 11;
    constexpr int8_t   misoPin        = 13;
    constexpr int8_t   resetPin       = -1;
    constexpr uint8_t  backlightPin   = 45;
    constexpr uint32_t spiFrequency   = 40000000;
#else  // BOARD_ILI9341_240x320 (original LCDWIKI board)
    constexpr int      width          = 320;    // landscape
    constexpr int      height         = 240;
    constexpr uint8_t  rotation       = 1;
    constexpr bool     invert         = false;
    constexpr uint8_t  backlightPin   = 21;
#endif

}  // namespace display

// -----------------------------------------------------------------------------
//  Timing: target frame rate and derived per-frame budget.
// -----------------------------------------------------------------------------
namespace timing {
    constexpr int      targetFps      = 30;
    constexpr uint32_t frameUs        = 1000000UL / targetFps;   // ~16667 us
}  // namespace timing

// -----------------------------------------------------------------------------
//  Palette: AURA's look is glowing cyan on a near-black background.
// -----------------------------------------------------------------------------
namespace color {
    constexpr uint16_t background   = rgb565(0, 0, 0);
    constexpr uint16_t eye          = rgb565(20, 160, 255);  // AURA blue
    constexpr uint16_t pupil        = rgb565(0, 0, 0);       // black eyeball
    constexpr uint16_t catchlight   = rgb565(235, 252, 255); // pupil highlight
    constexpr uint16_t love         = rgb565(255, 70, 110);
    constexpr uint16_t error        = rgb565(255, 60, 60);
    constexpr uint16_t star         = rgb565(255, 205, 40);  // celebrate gold
}  // namespace color

// -----------------------------------------------------------------------------
//  Eye geometry and on-screen face layout.
// -----------------------------------------------------------------------------
namespace eye {
    constexpr float width      = 84.0f;
    constexpr float height     = 96.0f;
    constexpr float radius     = 30.0f;
    constexpr float gap        = 52.0f;    // space between the two eyes
    constexpr float pupilScale = 0.40f;    // pupil size vs eye
    constexpr float pupilRange = 22.0f;    // max pupil travel from centre (px)

    // Vertical placement on the panel (eyes above centre, mouth below).
    constexpr int   centerY    = display::height / 2 - 20;
}  // namespace eye

// -----------------------------------------------------------------------------
//  Mouth geometry.
// -----------------------------------------------------------------------------
namespace mouth {
    constexpr float defaultWidth = 46.0f;  // px
    constexpr int   centerY      = display::height / 2 + 70;
}  // namespace mouth

// -----------------------------------------------------------------------------
//  Sprite buffer sizes (off-screen draw targets). These consume RAM; if boot
//  fails for want of heap, shrink the book sprite first.
// -----------------------------------------------------------------------------
namespace sprite {
    constexpr int eyeWidth   = 130;   // per eye  (~39 KB @ 16bpp)
    constexpr int eyeHeight  = 150;
    constexpr int mouthWidth = 170;   // mouth    (~24 KB)
    constexpr int mouthHeight = 70;
    constexpr int bookWidth  = 190;   // book     (~53 KB)
    constexpr int bookHeight = 140;
}  // namespace sprite

// -----------------------------------------------------------------------------
//  Blink timing (milliseconds).
// -----------------------------------------------------------------------------
namespace blink {
    constexpr uint32_t minGap  = 2200;   // shortest wait between blinks
    constexpr uint32_t maxGap  = 6000;   // longest wait between blinks
    constexpr uint32_t fastMs  = 130;    // quick blink duration
    constexpr uint32_t slowMs  = 380;    // slow / sleepy blink duration
}  // namespace blink

// -----------------------------------------------------------------------------
//  Idle motion: saccades (small darting eye moves), micro-jitter, breathing.
// -----------------------------------------------------------------------------
namespace idle {
    constexpr uint32_t saccadeMinGap = 1400;
    constexpr uint32_t saccadeMaxGap = 4200;
    constexpr uint32_t saccadeMs     = 220;
    constexpr float    microJitter   = 2.5f;    // px of constant tiny movement
    constexpr uint32_t breathPeriodMs = 3800;
    constexpr float    breathAmplitude = 4.0f;  // px vertical bob
}  // namespace idle

// -----------------------------------------------------------------------------
//  Book / focus-mode scene.
// -----------------------------------------------------------------------------
namespace book {
    constexpr uint16_t cover     = rgb565(15, 70, 140);
    constexpr uint16_t page      = rgb565(235, 230, 210);
    constexpr uint16_t flip      = rgb565(214, 207, 184);
    constexpr uint16_t line      = rgb565(150, 150, 150);
    constexpr uint16_t progress  = color::eye;
    constexpr uint32_t flipEveryMs = 4000;   // interval between page turns
    constexpr uint32_t flipMs      = 900;    // page-turn animation duration
}  // namespace book

// -----------------------------------------------------------------------------
//  Battery limits (percent). Thresholds for the on-screen / reported state.
// -----------------------------------------------------------------------------
namespace battery {
    constexpr float lowPercent   = 20.0f;    // warn at or below this
    constexpr float fullPercent  = 99.0f;    // treat as full at or above this
    constexpr uint32_t pollMs    = 5000;     // how often to sample
}  // namespace battery

// -----------------------------------------------------------------------------
//  Backlight limits (PWM duty, 0..255).
// -----------------------------------------------------------------------------
namespace backlight {
    constexpr uint8_t min      = 10;    // never fully off while awake
    constexpr uint8_t max      = 255;
    constexpr uint8_t defaultLevel = 255;
}  // namespace backlight

// -----------------------------------------------------------------------------
//  Hardware wiring, per board. Pins confirmed from each board's manual/wiki.
//  Added so the hardware managers read their pins from Config, never hard-code.
//  Fields common to all boards let a manager stay board-agnostic:
//    imu::present       - false when the board has no IMU (manager stays idle)
//    audio::pinEnable   - amp-enable GPIO, or 0xFF if none
//    audio::pinMclk     - I2S master clock GPIO, or 0xFF if none
//    batteryHw::adcPin  - battery-sense GPIO, or 0xFF to disable monitoring
// -----------------------------------------------------------------------------
namespace hw {

constexpr uint8_t kNoPin = 0xFF;

#if defined(BOARD_S3_LCDWIKI_ILI9341)
// ======================= LCDWIKI 2.8" ESP32-S3 (ES3C28P) =====================
namespace imu {                              // this board has NO IMU
    constexpr bool     present     = false;
    constexpr uint8_t  pinScl      = 15;     // board peripheral I2C (touch) — unused
    constexpr uint8_t  pinSda      = 16;
    constexpr uint8_t  pinInt1     = kNoPin;
    constexpr uint8_t  pinInt2     = kNoPin;
    constexpr uint8_t  i2cAddress  = 0x6B;
    constexpr uint32_t i2cClockHz  = 400000;
}  // namespace imu

namespace audio {                            // I2S speaker path (manual pin table)
    constexpr uint8_t  pinBck      = 5;      // IO5  I2S bit clock
    constexpr uint8_t  pinLrck     = 7;      // IO7  I2S word select (L/R)
    // The LCDWIKI table names DI/DO from the ES8311 codec's perspective.
    // Therefore codec DO (IO6) is ESP32 DIN, and codec DI (IO8) is ESP32 DOUT.
    constexpr uint8_t  pinDout     = 8;      // ESP32 -> ES8311 DAC
    constexpr uint8_t  pinDin      = 6;      // ES8311 ADC -> ESP32
    constexpr uint8_t  pinMclk     = 4;      // IO4  I2S master clock
    constexpr uint8_t  pinEnable   = 1;      // IO1  amp enable, ACTIVE LOW
    constexpr uint8_t  pinSda      = 16;     // shared I2C SDA
    constexpr uint8_t  pinScl      = 15;     // shared I2C SCL
    constexpr uint8_t  i2cAddress  = 0x18;   // ES8311
    constexpr uint32_t i2cClockHz  = 400000;
    constexpr bool     enableActiveLow = true;
    constexpr uint32_t sampleRate  = 16000;  // Hz
    constexpr uint16_t frameSamples = 320;   // 20 ms at 16 kHz
    constexpr uint8_t  defaultVolume = 68;   // ES8311 0..100
}  // namespace audio

namespace touch {                            // FT6336 on the shared I2C bus
    constexpr bool     present       = true;
    constexpr uint8_t  pinSda        = 16;
    constexpr uint8_t  pinScl        = 15;
    constexpr uint8_t  pinInt        = 17;
    constexpr uint8_t  pinRst        = 18;
    constexpr uint8_t  i2cAddress    = 0x38;
    constexpr uint16_t rawWidth      = 240;
    constexpr uint16_t rawHeight     = 320;
    constexpr uint16_t wireTimeoutMs = 20;
    constexpr uint16_t pressedPollMs = 24;
    constexpr uint16_t idleSafetyPollMs = 120;
    constexpr uint16_t tapMaxMs      = 450;
    constexpr uint16_t multiTapGapMs = 360;
    constexpr uint16_t longPressMs   = 1000;
    constexpr uint16_t stationaryTolerancePx = 28;
    constexpr uint16_t multiTapDistancePx = 55;
    constexpr uint16_t swipeMinDistancePx = 60;
    constexpr uint16_t swipeMaxMs    = 1100;
}  // namespace touch

namespace batteryHw {                        // IO9 battery-sense ADC (manual)
    constexpr uint8_t adcPin       = 9;      // confirmed from manual
    // Divider ratio not stated in the manual; 2.0 is the common design for these
    // boards. Calibrate against a measured voltage if precision matters.
    constexpr float   dividerRatio = 2.0f;   // <-- calibrate if needed
    constexpr float   emptyVolts   = 3.30f;
    constexpr float   fullVolts    = 4.20f;
    constexpr float   chargeVolts  = 4.15f;
}  // namespace batteryHw

#else
// ================= Waveshare ESP32-S3-Touch-LCD-2.8 (default) =================
namespace imu {                              // QMI8658 6-axis IMU (shared I2C bus)
    constexpr bool     present     = true;
    constexpr uint8_t  pinScl      = 10;     // IMU_SCL
    constexpr uint8_t  pinSda      = 11;     // IMU_SDA
    constexpr uint8_t  pinInt1     = 13;     // IMU_INT1 (unused for now)
    constexpr uint8_t  pinInt2     = 12;     // IMU_INT2 (unused for now)
    constexpr uint8_t  i2cAddress  = 0x6B;   // QMI8658; try 0x6A if WHO_AM_I fails
    constexpr uint32_t i2cClockHz  = 400000;
}  // namespace imu

namespace audio {                            // PCM5101A I2S DAC -> onboard speaker
    constexpr uint8_t  pinBck      = 48;     // I2S_BCK
    constexpr uint8_t  pinLrck     = 38;     // I2S_LRCK
    constexpr uint8_t  pinDin      = 47;     // I2S_DIN
    constexpr uint8_t  pinMclk     = kNoPin; // no external MCLK routed
    constexpr uint8_t  pinEnable   = kNoPin; // no separate amp-enable pin
    constexpr bool     enableActiveLow = true;
    constexpr uint32_t sampleRate  = 16000;  // Hz
    constexpr uint8_t  defaultVolume = 160;  // 0..255
}  // namespace audio

namespace touch {                            // disabled for alternate profile
    constexpr bool     present       = false;
    constexpr uint8_t  pinSda        = kNoPin;
    constexpr uint8_t  pinScl        = kNoPin;
    constexpr uint8_t  pinInt        = kNoPin;
    constexpr uint8_t  pinRst        = kNoPin;
    constexpr uint8_t  i2cAddress    = 0x38;
    constexpr uint16_t rawWidth      = 240;
    constexpr uint16_t rawHeight     = 320;
    constexpr uint16_t wireTimeoutMs = 20;
    constexpr uint16_t pressedPollMs = 24;
    constexpr uint16_t idleSafetyPollMs = 120;
    constexpr uint16_t tapMaxMs      = 450;
    constexpr uint16_t multiTapGapMs = 360;
    constexpr uint16_t longPressMs   = 1000;
    constexpr uint16_t stationaryTolerancePx = 28;
    constexpr uint16_t multiTapDistancePx = 55;
    constexpr uint16_t swipeMinDistancePx = 60;
    constexpr uint16_t swipeMaxMs    = 1100;
}  // namespace touch

namespace batteryHw {                        // voltage-sense ADC
    // The 2.8 wiki table does not list the battery-sense pin (GPIO1 is touch on
    // this board), so it stays UNSET and BatteryManager runs "unknown".
    constexpr uint8_t adcPin       = kNoPin; // <-- SET FROM SCHEMATIC TO ENABLE
    constexpr float   dividerRatio = 3.0f;   // (200K + 100K) / 100K, per Waveshare
    constexpr float   emptyVolts   = 3.30f;
    constexpr float   fullVolts    = 4.20f;
    constexpr float   chargeVolts  = 4.15f;
}  // namespace batteryHw

#endif

}  // namespace hw

}  // namespace cfg
}  // namespace aura
