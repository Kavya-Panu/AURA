AURA Firmware — Full Replacement, Buffered Graphics
=====================================================

Target board
------------
LCDWIKI / ES3C28P ESP32-S3 2.8-inch capacitive-touch board
ILI9341V, 240x320 native panel, used in 320x240 landscape mode.

What this build fixes
---------------------
1. Red/orange graphics and white background:
   The panel uses inverted colour polarity, so display inversion is enabled.
2. Heavy flickering:
   Every frame is drawn into a 320x240 RGB565 RAM canvas first and transferred
   to the LCD in one SPI transaction.
3. Boot scene stuck:
   The main loop now runs the face renderer at a paced 30 FPS, so all animation
   timers receive valid elapsed time.

Required Arduino libraries
--------------------------
- Adafruit GFX Library
- Adafruit ILI9341
- Adafruit BusIO

Arduino IDE settings
--------------------
Board: ESP32S3 Dev Module
USB CDC On Boot: Enabled
Flash Size: 16MB
PSRAM: Disabled
Serial Monitor: 115200 baud
Line ending: New Line

Expected boot output
--------------------
AURA_BOOT_BUFFERED
AURA_READY

Serial commands to test
-----------------------
STATUS
PING
FACE NEUTRAL
FACE HAPPY
FACE EXCITED
FACE ANGRY
FACE LOVE
LOOK LEFT
LOOK RIGHT
LOOK CENTER
BLINK
DOUBLE_BLINK
BOOK START
BOOK STOP
BRIGHTNESS 128

Important
---------
If the LCD displays FRAMEBUFFER ERROR, the 320x240 canvas could not be allocated.
Do not enable audio or other large RAM users until the graphics stage is stable.

Blue-eye correction
-------------------
The active LCDWIKI board profile now enables panel inversion. This changes the
incorrect white background/red eyes into the intended black background/cyan-blue
eyes. The framebuffer and 30 FPS anti-flicker implementation are unchanged.
