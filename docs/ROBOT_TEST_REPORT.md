# AURA robot reliability audit — 8 September 2026

## Confirmed working

- Touch: single tap Happy, multiple taps Angry, slide Love, hold Sleep/Wake. The project owner confirmed every gesture and the five-second Angry reset.
- Robot speaker: The project owner confirmed both spoken test sentences were clear. The earlier short tones were not audible, so tones alone are not treated as proof of audible output.
- Five-second timer: The project owner confirmed the countdown advanced, the alert spoke, and the normal face returned afterwards.
- USB microphone streaming: repeated capture/playback cycles completed; the final stream check collected 55 frames with no malformed packets or clipping.
- Display commands: 15 emotions, blink/gaze/sleep commands, scenes, brightness, and music visualizer commands were accepted by the robot.
- THINK commands and timer cleanup were delivered while the microphone stayed open. Angry returned to Neutral after approximately five seconds.
- Small head movement and the built-in motor test completed at the protocol level; this is not a mechanical load or endurance certification.
- Full software startup: COM14 handshake, ES8311 microphone/speaker, GPU Whisper, local Qwen, face tracking, saved face profile, weather, search, and study-distraction monitoring initialized.
- Live weather resolved Manchester, London, and Liverpool separately. A final typed Manchester question passed through the full application and started robot speech without a playback error.
- Web search returned results; camera face detection worked on 12 sampled frames; the object detector and image-search credentials initialized.
- Vosk recognized synthetic wake and all three stop phrases. Whisper correctly transcribed a synthetic spoken weather question.

## Fixes applied

1. Retain incomplete USB microphone packets until their newline arrives, instead of losing partial audio on a serial timeout. Oversized malformed lines recover safely.
2. Keep handshake traffic exclusive, then allow urgent face/timer controls through during audio streaming. This fixes queued countdown cleanup and THINK commands being held behind microphone traffic.
3. Coalesce old gaze, head-position, and music-level updates so only the latest queued value remains.
4. Refresh changed expressions and timer scenes during microphone operation. Thinking animation receives periodic updates without constantly redrawing the ordinary listening face.
5. Reject digital silence and constant ADC samples before Whisper. The reproduced silent-input "Thank you" hallucination now produces an empty transcript.
6. Reject blank/flat camera images and generic-only image-search labels such as colors, materials, or hands instead of presenting them as an identified held object.

The firmware was compiled and uploaded successfully. Previous firmware source files and the previous compiled application binary are preserved in a local checkpoint folder that is not published. The binary is an application image, not a complete flash backup.

## Automated checks

90 targeted regression tests passed across serial framing, audio command delivery, ESP32 audio, listening, wake/stop detection, weather, search, reminders, focus sessions, distraction monitoring, visual identification, face following, and brain-to-hardware integration.

The entire historical repository test suite is NOT green: an earlier file-by-file run found 65 passing test files and 30 failing files, largely older scaffold imports, outdated interface assumptions, and environment-dependent tests. Those are not included in the 90-test result, and this report does not claim every old test was repaired.

## Still requires real-world checks

- Actual wake-to-question capture at the desired microphone distance and interruption while the robot is speaking. Synthetic tests cannot establish real-room echo, accent, or range performance.
- Phone-use and absence detection during a real study session; timing, cooldown, and no-camera behavior have automated coverage.
- Reliable identification of arbitrary held objects. Cloud lookup works, but generic matching is not equivalent to guaranteed Google Lens accuracy.
- Spotify playback end to end. Spotify and audio capture are available, but no active Spotify session was present during the audit. Visualizer command delivery alone does not prove music playback.
- Long unattended operation, speaker quality at every volume, and mechanical endurance.

## Start and retest

### DC motor emotion reactions — 8 September 2026

**Retired on 9 September 2026 at the user's request.** The physical motor did not rotate during the command tests. DC motor output is now disabled at firmware build time, with SLP and both driver inputs held low. The historical checks below describe commanded output only. Head-servo functionality remains enabled.

Installed on the existing DRV8833 top motor; head-servo configuration and buffered speaker settings are unchanged.

- Happy: one gentle forward pulse (50% PWM, 250 ms hold).
- Excited/Celebrate: one longer forward pulse (75%, 1100 ms hold).
- Love: one gentle forward pulse (45%, 650 ms hold).
- Angry: two forward pulses (65%, 200 ms hold each, 250 ms gap).
- Hold times exclude smooth acceleration/deceleration. These are PWM commands, not measured motor RPM.
- Question capture, speaker playback, Thinking, Listening, Sleep/Sleepy, and non-idle scenes suppress movement. Suppressed reactions are not replayed later. Idle wake-word monitoring permits brief touch reactions.
- Patterns follow actual emotion changes, including touch; repeated identical commands do not restart a pulse.

An initial hardware-link test caught loop-dependent ramp timing. The ramp now accounts for elapsed time, with each speed adjustment capped at 10 percentage points. After recompiling/uploading, `verify_dc_emotions.py` passed all four pulse-count/stop checks, the question-capture quiet guard, no stale replay after unmuting, and the sleep stop check. Peaks reported by firmware were 50, 75, 45, and 65 respectively. This confirms controller output state, not independently measured shaft motion; user visual confirmation was requested. 45 selected voice, audio, serial, head-tracking, and integration tests passed, including two new capture-guard tests.

Pre-change copies are under `software/checkpoints/dc_emotions_20260908/`. To test manually with AURA running, use a tap (Happy), multiple taps (Angry), or a slide (Love), keeping the motor clear. Question recording and speech take priority over movement.

### Buffered speaker follow-up

After quiet isolated speech tests sounded clear but normal answers remained unclear, the firmware audio scheduler was updated and uploaded:

- Handle up to four queued commands before microphone/display work, instead of just one.
- Wait for three 20 ms speaker packets at stream start to absorb short transport delays.
- Configure an explicit 120 ms DMA ring and allow the final samples to drain before muting.
- Retry partial I2S writes and count write failures and queue drops.
- Expose `AUDIO STATS` for repeatable physical-link diagnostics.

`verify_buffered_speaker.py` passed a one-frame short clip, an aborted stream, and a 9.21-second spoken sentence while the microphone remained active. The sentence delivered all 461 packets with zero queue drops and zero I2S write errors. The queue wait counter was 77; this counts 40 ms queue waits and is NOT a measurement of DAC underruns. The project owner confirmed the sentence was clear and loud enough. The test used existing volume 75; no positive-gain boost or new volume mapping was introduced. 43 relevant Python regression tests also passed.

The prior firmware source is saved under `software/checkpoints/audio_stream_20260908/`. These changes leave microphone gain, touch handling, head limits, and expression artwork unchanged.

### Two-step wake interaction

Say only "Hey AURA", wait for the spoken "Hmm?", then ask the question or command. The wake stream is closed before the acknowledgement and is not replayed into question transcription. Fresh question capture begins after the acknowledgement and a short speaker-tail delay. The existing five-second follow-up conversation window remains unchanged.

47 relevant voice, serial/audio, head-tracking, and integration tests passed after this change. End-to-end audible acknowledgement and question capture still need the user's live confirmation. If USB is disconnected, reconnect the robot and restart AURA before testing.

### Head tracking follow-up

The audio priority gate was still delaying LOW-priority head tracking while the wake microphone stayed open. Head targets are now promoted to HIGH priority and still coalesced to the latest position. All queued commands remain blocked during audio handshakes; ordinary gaze traffic retains its existing policy. The existing pause during question capture and speaker playback is unchanged.

26 relevant tests passed, including two new regression tests for head delivery with the microphone open and handshake isolation. A physical-link check sent small targets 86, 104, and 95 degrees while capturing 84, 80, and 80 microphone frames respectively, with no queued commands remaining. The project owner confirmed that the head moved left, right, and back to centre.

Start normal AURA using `START_AURA.bat` in this folder. Do not open a second copy or Arduino Serial Monitor while AURA owns COM14.

For the dedicated robot self-test, close AURA first and use `RUN_ROBOT_SELF_TEST.bat`. This test can move the head and top motor: keep both clear. Its Python entry point also accepts `--skip-motion`. The test restores ordinary display/audio settings afterwards and does not save microphone recordings.

