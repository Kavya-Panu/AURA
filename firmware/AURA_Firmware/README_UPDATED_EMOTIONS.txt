AURA Updated Emotions Build
============================

This complete Arduino project implements the approved emotion preview while
preserving the existing BlinkSystem and the continuous book-page animation.

Updated expressions
-------------------
NEUTRAL
- Blue rounded eyes, black pupils, white catchlights, short white mouth.

HAPPY
- Curved smiling eyes with no pupils.
- White smile.
- Normal blink animation remains enabled.

EXCITED
- Open bright eyes.
- Pink cheek blush.
- White open smile with dark interior and pink tongue.

THINKING
- Eyes look upward.
- Same-size processing dots above the right eye:
  .  then ..  then ...  then ...., continuously looping.

CURIOUS
- Lively side-to-side gaze.
- Small white O-shaped mouth.

WORRIED
- Worried white eyebrows.
- Downturned white mouth.

CONFUSED
- Uneven/slanted eye expression.
- Small white question mark above the right eye.
- Slanted white mouth.

ANGRY
- Strong white angry eyebrows.
- Downturned white mouth.

LOVE
- Pink heart pupils.
- Pink blush.
- Gentle white smile.

SLEEPY
- Half-closed blue eyes without pupils.
- White z, Z, Z increasing in size.
- Short white mouth.

UNCHANGED
---------
- BlinkSystem and its timing/animation.
- Focus mode book scene.
- Continuous page turning in focus mode.
- Book scene contains no eyes.

Required Arduino libraries
--------------------------
- Adafruit GFX Library
- Adafruit ILI9341
- Adafruit BusIO

Board settings
--------------
Board: ESP32S3 Dev Module
USB CDC On Boot: Enabled
Flash Size: 16MB
PSRAM: Disabled
Serial Monitor: 115200 baud
Line ending: New Line

Useful test commands
--------------------
FACE NEUTRAL
FACE HAPPY
FACE EXCITED
FACE THINKING
FACE CURIOUS
FACE WORRIED
FACE CONFUSED
FACE ANGRY
FACE LOVE
FACE SLEEPY
BLINK
BOOK START
BOOK STOP
