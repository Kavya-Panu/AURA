AURA Voice - Siri-Style Upgrade
===============================

Start with SIRI_STYLE_VOICE_GUIDE.txt. This version includes adaptive pause
detection, room-noise calibration, conversation mode and wake-word-style mode.

What works
----------
- Press Enter to record one question using the laptop microphone.
- Speech ends after an adaptive 1.25-1.8 seconds of silence.
- faster-whisper transcribes locally.
- Qwen3 8B answers locally through Ollama.
- AURA speaks the answer through the laptop speaker with pyttsx3.
- The ESP32 shows CURIOUS while listening, THINKING while generating, and an
  answer-appropriate emotion while speaking.
- Typed questions and all existing slash commands still work.

Why this is push-to-talk
------------------------
This is the reliable first voice stage. The microphone opens only while you are
asking a question, so AURA cannot hear and re-transcribe its own speaker output.
A true "Hey AURA" wake-word loop is the next stage.

Important hardware boundary
---------------------------
This stage uses the LAPTOP microphone and LAPTOP speaker. The ESP32 board's
built-in I2S microphone/speaker require a separate USB audio-streaming firmware
protocol and are not used yet.

Install
-------
1. Close Arduino Serial Monitor.
2. Double-click INSTALL_VOICE.bat.
3. Double-click START_AURA_VOICE.bat.
4. The first startup downloads the Whisper base.en model.
5. At the prompt, press Enter, speak, and stop talking.

Commands
--------
[Enter]            Speak one question
/listen            Speak one question
/mics              List microphone device indexes
/say Hello         Test text-to-speech
/stop              Stop AURA speaking
/emotion HAPPY     Set face directly
/blink             Blink
/focus on          Start book mode
/focus off         Stop book mode
/status            ESP32 status
/quit              Exit

Selecting a microphone
----------------------
Run /mics, note the desired index, then edit aura_settings.json:
    "microphone_index": 3

Troubleshooting
---------------
No microphone:
- Run /mics.
- Check Windows Settings > Privacy & security > Microphone.
- Ensure desktop apps are allowed to use the microphone.

Slow first run:
- Whisper downloads and loads its model only on first startup.
- Qwen is also warmed before the prompt appears.

Whisper settings:
- Default is base.en on CPU int8, which avoids competing with Qwen for the
  RTX GPU's VRAM.
- For faster but less accurate recognition, change whisper_model to tiny.en.
