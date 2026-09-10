# AURA Brain + ESP32 Integration

This package connects the existing AURA Python brain to the physical ESP32 face.

## End-to-end path

```text
Keyboard question
    -> EventBus
    -> BrainManager
    -> Ollama Qwen 3 8B
    -> BrainHardwareBridge
    -> HardwareManager
    -> USB serial
    -> ESP32 face emotion
```

This first integration prints the answer on the laptop. It intentionally leaves
microphone, speech recognition and TTS for the next stage so the brain-to-face
protocol can be validated independently.

## Firmware protocol now matched

The Python hardware layer now sends the commands your current firmware accepts:

- `NORMAL` is converted to `NEUTRAL`
- continuous gaze becomes `LOOK LEFT/RIGHT/UP/DOWN/CENTER`
- one blink becomes `BLINK`
- multiple blinks become `DOUBLE_BLINK`
- focus becomes `BOOK START` / `BOOK STOP`
- unsupported `MOUTH:*` traffic is suppressed for now

## Setup

1. Flash the latest AURA firmware to the ESP32.
2. Close Arduino Serial Monitor. Only one program can own the COM port.
3. Install Python dependencies:

```powershell
python -m pip install -r requirements_brain.txt
```

4. Install/start Ollama and make sure the model exists:

```powershell
ollama pull qwen3:8b
ollama run qwen3:8b
```

You may stop the interactive `ollama run` session after the model responds; the
Ollama service remains available in the background.

5. Edit `aura_settings.json` if the ESP32 is not on `COM14`.

6. Start AURA:

```powershell
python run_aura_brain.py
```

or double-click:

```text
START_AURA_BRAIN.bat
```

## First validation

At startup you should see:

```text
ESP32 face link: CONNECTED (PONG received)
Brain provider: Ollama / qwen3:8b
```

Ask:

```text
What is Ohm's law?
```

Expected physical behavior:

1. Face changes to THINKING while Qwen generates.
2. Answer prints in the terminal.
3. Face changes to an emotion selected from the answer.

## Built-in commands

```text
/emotion HAPPY
/blink
/focus on
/focus off
/status
/mode TEACHER
/quit
```

## Diagnostic modes

Test without Ollama:

```powershell
python run_aura_brain.py --mock-brain
```

Test without physical ESP32:

```powershell
python run_aura_brain.py --mock-hardware --mock-brain
```

Specify another port/model:

```powershell
python run_aura_brain.py --port COM6 --model qwen3:8b
```
