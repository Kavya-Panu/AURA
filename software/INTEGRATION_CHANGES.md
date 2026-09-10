# Integration changes

## Added

- `run_aura_brain.py`: real end-to-end console launcher.
- `aura_settings.json`: COM port, model and mode settings.
- `START_AURA_BRAIN.bat`: Windows one-click launcher.
- `requirements_brain.txt`: `pyserial` and `ollama`.
- `integration/brain_hardware_bridge.py`: event-driven brain-to-face bridge.
- `hardware/esp32_protocol.py`: one source of truth for firmware commands.
- Integration tests for the ESP32 protocol and brain/hardware event flow.

## Corrected

- Python face commands now match the current ESP32 firmware.
- `NORMAL` is translated to `NEUTRAL`.
- Gaze is translated to `LOOK LEFT/RIGHT/UP/DOWN/CENTER`.
- Blink requests are translated to `BLINK` or `DOUBLE_BLINK`.
- Focus mode is translated to `BOOK START` / `BOOK STOP`.
- Unsupported `MOUTH:*` messages are suppressed until firmware visemes exist.
- Core RobotEvent constants were merged to include Brain and Hardware events.
- Default local model changed to `qwen3:8b`.

## Validated

- Python compile check passed.
- 14 focused protocol, bridge and face-driver tests passed.
- Mock end-to-end launch passed:
  question -> BrainManager -> answer -> face-emotion events -> mock ESP32.
