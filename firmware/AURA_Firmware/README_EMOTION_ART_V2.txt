AURA Emotion Art V2
===================

This build replaces the old parameter-only face rendering with a dedicated
ExpressionRenderer. Every emotion now has visibly different eye geometry,
pupils, eyebrows, symbols and mouth art.

IMPORTANT
---------
After boot the robot still starts in NEUTRAL, so the first screen is expected
to look similar. Use the Serial Monitor at 115200 baud with New Line enabled.
You can now use either command style:

    HAPPY
    FACE HAPPY

Direct test commands
--------------------
NEUTRAL
HAPPY
EXCITED
THINKING
CURIOUS
WORRIED
CONFUSED
ANGRY
LOVE
SLEEPY
BLINK
BOOK START
BOOK STOP

Visual changes
--------------
HAPPY: cyan smiling-eye arcs and white smile.
EXCITED: open eyes, pink blush and open mouth with tongue.
THINKING: pupils look upward and . / .. / ... / .... loops above right eye.
CURIOUS: pupils scan left and right with a small O mouth.
WORRIED: raised worried eyebrows and frown.
CONFUSED: unequal eyes, question mark and slanted mouth.
ANGRY: strong inward eyebrows and frown.
LOVE: pink heart pupils, blush and smile.
SLEEPY: half-closed eyes with z, Z, Z.

Unchanged
---------
BlinkSystem timing/state machine is unchanged.
Focus mode still shows only the continuously turning book pages, with no eyes.

Expected Serial boot line
-------------------------
AURA_EMOTION_ART_V2
AURA_READY
