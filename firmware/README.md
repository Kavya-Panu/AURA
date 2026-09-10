# AURA ESP32-S3 firmware

Open `AURA_Firmware/AURA_Firmware.ino` in Arduino IDE and select an ESP32-S3
board. The working prototype was built with USB CDC on boot enabled, 16 MB flash,
PSRAM disabled and an upload speed of 921600 baud.

Install these libraries before compiling:

- ESP32 Arduino core 3.3.10
- Adafruit GFX Library 1.12.6
- Adafruit ILI9341 1.6.3
- Adafruit TouchScreen
- Adafruit STMPE610
- Adafruit TSC2007
- ESP32Servo 3.2.1
- audio-driver 0.1.2 (ES8311 support)

The firmware controls the ILI9341 display, touch gestures, face animations,
ES8311 microphone and speaker, head servo, timer/countdown scenes and the serial
protocol used by the Python brain. The compiled `build/` folder and previous
firmware images are intentionally excluded.
