// =============================================================================
// AURA Firmware — buffered display build
// Target: LCDWIKI ES3C28P ESP32-S3 2.8-inch ILI9341V board
//
// Active modules:
//   - Flicker-free full-frame DisplayManager
//   - Face engine
//   - SerialManager
//   - CommandParser
//
// Battery, audio and IMU will be enabled after graphics/serial validation.
// =============================================================================
#include <Arduino.h>

#include "Config.h"
#include "FaceController.h"
#include "SerialManager.h"
#include "CommandParser.h"
#include "AudioManager.h"
#include "Base64Codec.h"
#include "HeadServoController.h"
#include "TopMotorController.h"
#include "TouchManager.h"

namespace {

using namespace aura;

struct Firmware {
    FaceController face;
    SerialManager serial;
    CommandParser parser;
    AudioManager audio;
    HeadServoController headServo;
    TopMotorController topMotor;
    TouchManager touch;
    uint32_t lastFrameMicros = 0;
    bool touchReactionActive = false;
    Emotion touchPreviousEmotion = Emotion::Neutral;
    Emotion touchReactionEmotion = Emotion::Neutral;
    uint32_t touchReactionUntilMs = 0;
    bool angryAutoReturnActive = false;
    uint32_t angryAutoReturnAtMs = 0;
    bool touchSuspendedMusic = false;
    bool motorQuiet = false;
    Emotion motorPreviousEmotion = Emotion::Neutral;
};

Firmware& firmware() {
    static Firmware fw;
    return fw;
}

constexpr float kMaxFrameMs = 100.0f;

void drawTouchReactionNow(Firmware& fw) {
    // One immediate buffered frame makes touch feel responsive even while the
    // normal display loop is paused to protect wake-word microphone quality.
    fw.face.update(0.0f);
    fw.lastFrameMicros = micros();
}

void startTouchReaction(Firmware& fw, Emotion emotion, uint32_t holdMs,
                        uint32_t nowMs) {
    fw.touchSuspendedMusic = fw.face.musicModeActive();
    if (fw.touchSuspendedMusic) fw.face.suspendMusicDisplay();
    Emotion previous = fw.face.currentEmotion();
    if (previous == Emotion::Sleep) {
        fw.face.wake();
        previous = Emotion::Neutral;
    }
    fw.touchPreviousEmotion = previous;
    fw.touchReactionEmotion = emotion;
    fw.touchReactionUntilMs = nowMs + holdMs;
    fw.touchReactionActive = true;
    fw.face.setEmotion(emotion);
    drawTouchReactionNow(fw);
}

void handleTouch(Firmware& fw, const TouchEvent& event, uint32_t nowMs) {
    if (event.gesture == TouchGesture::None) return;
    if (fw.face.currentScene() != SceneManager::Scene::Idle) return;

    switch (event.gesture) {
        case TouchGesture::Tap:
            startTouchReaction(fw, Emotion::Happy, 1300, nowMs);
            fw.face.blink();
            break;
        case TouchGesture::MultiTap:
            startTouchReaction(fw, Emotion::Angry, 5000, nowMs);
            fw.touchPreviousEmotion = Emotion::Neutral;
            break;
        case TouchGesture::Swipe:
            startTouchReaction(fw, Emotion::Love, 2200, nowMs);
            break;
        case TouchGesture::LongPress:
            fw.touchReactionActive = false;
            if (fw.face.currentEmotion() == Emotion::Sleep) {
                fw.face.wake();
                fw.face.resumeMusicDisplay();
            } else {
                if (fw.face.musicModeActive()) fw.face.suspendMusicDisplay();
                fw.face.sleep();
            }
            drawTouchReactionNow(fw);
            break;
        case TouchGesture::None:
            break;
    }
}

void updateTouchReaction(Firmware& fw, uint32_t nowMs) {
    if (!fw.touchReactionActive) return;
    if (fw.face.currentEmotion() != fw.touchReactionEmotion) {
        fw.touchReactionActive = false;
        return;
    }
    if (static_cast<int32_t>(nowMs - fw.touchReactionUntilMs) >= 0) {
        fw.touchReactionActive = false;
        fw.face.setEmotion(fw.touchPreviousEmotion);
        if (fw.touchSuspendedMusic) {
            fw.face.resumeMusicDisplay();
            fw.touchSuspendedMusic = false;
        }
        drawTouchReactionNow(fw);
    }
}

void updateAngryAutoReturn(Firmware& fw, uint32_t nowMs) {
    // Angry is always a short reaction, regardless of whether it came from
    // touch, voice, the laptop brain, or a direct serial command.
    if (fw.face.currentEmotion() != Emotion::Angry) {
        fw.angryAutoReturnActive = false;
        return;
    }

    if (!fw.angryAutoReturnActive) {
        fw.angryAutoReturnActive = true;
        fw.angryAutoReturnAtMs = nowMs + 5000UL;
        return;
    }

    if (static_cast<int32_t>(nowMs - fw.angryAutoReturnAtMs) >= 0) {
        fw.angryAutoReturnActive = false;
        fw.touchReactionActive = false;
        fw.face.setEmotion(Emotion::Neutral);
        drawTouchReactionNow(fw);
    }
}

bool handleHeadServoCommand(Firmware& fw, const char* line) {
    if (line == nullptr) return false;

    constexpr char prefix[] = "SERVO:HEAD:";
    if (strncmp(line, prefix, sizeof(prefix) - 1) != 0) return false;

    char* end = nullptr;
    const float angle = strtof(line + sizeof(prefix) - 1, &end);
    while (end != nullptr && (*end == ' ' || *end == '\t')) ++end;
    if (end == line + sizeof(prefix) - 1 || end == nullptr || *end != '\0'
            || angle < 0.0f || angle > 180.0f) {
        fw.serial.writeLine("ERR_INVALID_SERVO_ANGLE");
        return true;
    }

    fw.headServo.setTarget(angle);
    fw.serial.writeLine("OK");
    return true;
}

bool handleTopMotorCommand(Firmware& fw, const char* line) {
    if (line == nullptr) return false;

    if (strcmp(line, "MOTOR:TOP:QUIET:ON") == 0) {
        fw.motorQuiet = true;
        fw.topMotor.stop();
        fw.serial.writeLine("OK MOTOR_QUIET");
        return true;
    }
    if (strcmp(line, "MOTOR:TOP:QUIET:OFF") == 0) {
        fw.motorQuiet = false;
        // Do not replay an emotion suppressed during an audio session.
        fw.motorPreviousEmotion = fw.face.currentEmotion();
        fw.serial.writeLine("OK MOTOR_REACTIONS_ENABLED");
        return true;
    }

    if (strcmp(line, "MOTOR:TOP:TEST") == 0) {
        if (!fw.topMotor.ready()) {
            fw.serial.writeLine("MOTOR ERROR NOT_READY");
        } else {
            fw.topMotor.startTest();
            fw.serial.writeLine("OK MOTOR_TEST_STARTED");
        }
        return true;
    }
    if (strcmp(line, "MOTOR:TOP:STOP") == 0) {
        fw.topMotor.stop();
        fw.serial.writeLine("OK MOTOR_STOPPED");
        return true;
    }
    if (strcmp(line, "MOTOR:TOP:STATUS") == 0) {
        char reply[64];
        snprintf(reply, sizeof(reply), "MOTOR TOP %s SPEED=%u TEST=%s",
                 fw.topMotor.running() ? "RUNNING" : "STOPPED",
                 fw.topMotor.speedPercent(),
                 fw.topMotor.testRunning() ? "YES" : "NO");
        fw.serial.writeLine(reply);
        return true;
    }

    constexpr char forwardPrefix[] = "MOTOR:TOP:FORWARD:";
    constexpr char reversePrefix[] = "MOTOR:TOP:REVERSE:";
    const char* valueText = nullptr;
    bool reverse = false;
    if (strncmp(line, forwardPrefix, sizeof(forwardPrefix) - 1) == 0) {
        valueText = line + sizeof(forwardPrefix) - 1;
    } else if (strncmp(line, reversePrefix, sizeof(reversePrefix) - 1) == 0) {
        valueText = line + sizeof(reversePrefix) - 1;
        reverse = true;
    } else {
        return false;
    }

    char* end = nullptr;
    const long percent = strtol(valueText, &end, 10);
    while (end != nullptr && (*end == ' ' || *end == '\t')) ++end;
    if (end == valueText || end == nullptr || *end != '\0'
            || percent < 0 || percent > 80) {
        fw.serial.writeLine("ERR_MOTOR_SPEED_USE_0_TO_80");
        return true;
    }

    if (!fw.topMotor.ready()) {
        fw.serial.writeLine("MOTOR ERROR DISABLED");
        return true;
    }
    if (reverse) {
        fw.topMotor.setReverse(static_cast<uint8_t>(percent));
    } else {
        fw.topMotor.setForward(static_cast<uint8_t>(percent));
    }
    fw.serial.writeLine("OK");
    return true;
}

void updateEmotionalMotor(Firmware& fw) {
    const Emotion emotion = fw.face.currentEmotion();
    const bool changed = emotion != fw.motorPreviousEmotion;
    fw.motorPreviousEmotion = emotion;
    if (!fw.topMotor.ready()) return;

    // Keep the driver asleep during speech/question capture and quiet scenes.
    // Idle wake-word monitoring can still receive short touch reactions.
    if (fw.motorQuiet || fw.audio.speakerActive()
            || fw.face.currentScene() != SceneManager::Scene::Idle
            || fw.face.musicModeActive()
            || emotion == Emotion::Thinking || emotion == Emotion::Listening
            || emotion == Emotion::Sleep || emotion == Emotion::Sleepy) {
        fw.topMotor.stop();
        return;
    }
    if (!changed) return;
    fw.topMotor.stop();
    switch (emotion) {
        case Emotion::Happy:    fw.topMotor.runPulse(50, 250); break;
        case Emotion::Excited:  fw.topMotor.runPulse(75, 1100); break;
        case Emotion::Celebrate:fw.topMotor.runPulse(75, 1100); break;
        case Emotion::Angry:    fw.topMotor.runPattern(65, 200, 2, 250); break;
        case Emotion::Love:     fw.topMotor.runPulse(45, 650); break;
        default: break;
    }
}

bool handleAudioCommand(Firmware& fw, const char* line) {
    if (line == nullptr) return false;

    if (strcmp(line, "AUDIO INFO") == 0) {
        fw.serial.writeLineImmediate(
            fw.audio.isReady()
                ? "AUDIO READY RATE=16000 FRAME=320 CODEC=ES8311"
                : "AUDIO ERROR CODEC_NOT_READY"
        );
        return true;
    }
    if (strcmp(line, "MIC START") == 0) {
        fw.topMotor.stop();
        if (fw.audio.startMicrophone()) {
            fw.serial.writeLineImmediate("MIC BEGIN 16000 320");
        } else {
            fw.serial.writeLineImmediate("AUDIO ERROR MIC_START_FAILED");
        }
        return true;
    }
    if (strcmp(line, "MIC STOP") == 0) {
        fw.audio.stopMicrophone();
        fw.serial.writeLineImmediate("MIC END");
        return true;
    }
    if (strcmp(line, "SPK BEGIN") == 0) {
        if (fw.audio.startSpeaker()) {
            fw.serial.writeLineImmediate("SPK READY");
        } else {
            fw.serial.writeLineImmediate("AUDIO ERROR SPK_START_FAILED");
        }
        return true;
    }
    if (strcmp(line, "AUDIO STATS") == 0) {
        char stats[128];
        snprintf(stats, sizeof(stats),
                 "AUDIO STATS FRAMES=%lu QUEUE_DROPS=%lu WRITE_ERRORS=%lu WAITS=%lu",
                 static_cast<unsigned long>(fw.audio.speakerFrames()),
                 static_cast<unsigned long>(fw.audio.speakerQueueDrops()),
                 static_cast<unsigned long>(fw.audio.speakerWriteErrors()),
                 static_cast<unsigned long>(fw.audio.speakerWaits()));
        fw.serial.writeLineImmediate(stats);
        return true;
    }
    if (strcmp(line, "SPK END") == 0) {
        fw.audio.stopSpeaker();
        fw.serial.writeLineImmediate("SPK DONE");
        return true;
    }
    if (strcmp(line, "SPK ABORT") == 0) {
        fw.audio.abortSpeaker();
        fw.serial.writeLineImmediate("SPK DONE");
        return true;
    }
    if (strncmp(line, "SPK:", 4) == 0) {
        int16_t pcm[cfg::hw::audio::frameSamples];
        const size_t bytes = base64::decode(
            line + 4,
            reinterpret_cast<uint8_t*>(pcm),
            sizeof(pcm)
        );
        if (bytes == 0 || (bytes % sizeof(int16_t)) != 0) {
            fw.serial.writeLine("AUDIO ERROR BAD_PCM_FRAME");
        } else {
            fw.audio.playMonoPcm(pcm, bytes / sizeof(int16_t));
        }
        return true;
    }
    if (strncmp(line, "AUDIO VOLUME ", 13) == 0) {
        fw.audio.setVolume(static_cast<uint8_t>(atoi(line + 13)));
        fw.serial.writeLine("OK");
        return true;
    }
    if (strcmp(line, "AUDIO MUTE") == 0) {
        fw.audio.mute();
        fw.serial.writeLine("OK");
        return true;
    }
    if (strcmp(line, "AUDIO UNMUTE") == 0) {
        fw.audio.unmute();
        fw.serial.writeLine("OK");
        return true;
    }
    return false;
}

bool handleMusicCommand(Firmware& fw, const char* line) {
    if (line == nullptr) return false;

    if (strcmp(line, "MUSIC START") == 0) {
        fw.touchReactionActive = false;
        fw.touchSuspendedMusic = false;
        fw.face.startMusicMode();
        return true;
    }
    if (strcmp(line, "MUSIC STOP") == 0) {
        fw.touchReactionActive = false;
        fw.touchSuspendedMusic = false;
        fw.face.stopMusicMode();
        fw.face.setEmotion(Emotion::Neutral);
        return true;
    }
    if (strcmp(line, "MUSIC HIDE") == 0) {
        fw.face.suspendMusicDisplay();
        return true;
    }
    if (strcmp(line, "MUSIC SHOW") == 0) {
        fw.face.resumeMusicDisplay();
        return true;
    }
    if (strcmp(line, "MUSIC PAUSE 1") == 0) {
        fw.face.setMusicPaused(true);
        return true;
    }
    if (strcmp(line, "MUSIC PAUSE 0") == 0) {
        fw.face.setMusicPaused(false);
        return true;
    }
    if (strncmp(line, "MUSIC LEVEL ", 12) == 0) {
        const int value = atoi(line + 12);
        fw.face.setMusicLevel(static_cast<uint8_t>(constrain(value, 0, 100)));
        return true;
    }
    if (strncmp(line, "MUSIC META:", 11) == 0) {
        uint8_t decoded[192] = {};
        const size_t count = base64::decode(
            line + 11,
            decoded,
            sizeof(decoded) - 1
        );
        if (count == 0) return true;
        decoded[count] = '\0';
        char* title = reinterpret_cast<char*>(decoded);
        char* artist = strchr(title, '\n');
        char emptyArtist[1] = {};
        if (artist != nullptr) {
            *artist = '\0';
            ++artist;
        } else {
            artist = emptyArtist;
        }
        fw.face.setMusicMetadata(title, artist);
        return true;
    }
    return false;
}

void streamMicrophone(Firmware& fw) {
    if (!fw.audio.microphoneActive()) return;

    int16_t pcm[cfg::hw::audio::frameSamples];
    const size_t samples = fw.audio.readMicrophoneFrame(
        pcm,
        cfg::hw::audio::frameSamples
    );
    if (samples == 0) return;

    // 640 PCM bytes become 856 Base64 characters, plus the MIC: prefix.
    char line[4 + ((cfg::hw::audio::frameSamples * 2 + 2) / 3) * 4 + 1];
    memcpy(line, "MIC:", 4);
    const size_t encoded = base64::encode(
        reinterpret_cast<const uint8_t*>(pcm),
        samples * sizeof(int16_t),
        line + 4,
        sizeof(line) - 4
    );
    if (encoded > 0) fw.serial.writeLineImmediate(line);
}

}  // namespace

void setup() {
    Firmware& fw = firmware();

    fw.serial.begin();
    delay(500);
    fw.serial.writeLine("AURA_EMOTION_ART_V2");

    if (!fw.face.begin()) {
        fw.serial.writeLine("ERR_DISPLAY_OR_FRAMEBUFFER_INIT");
        return;
    }

    fw.parser.begin();
    fw.parser.registerFaceController(fw.face);

    if (!fw.headServo.begin()) {
        fw.serial.writeLine("SERVO ERROR HEAD_INIT_FAILED");
    } else {
        fw.serial.writeLine("SERVO READY HEAD GPIO=21 CENTER=95");
    }

    if (!fw.topMotor.begin()) {
        fw.serial.writeLine(TopMotorController::kEnabled
            ? "MOTOR ERROR PWM_INIT_FAILED" : "MOTOR DISABLED");
    } else {
        fw.serial.writeLine("MOTOR READY TOP DRIVER=DRV8833 SLP=14 IN1=2 IN2=3 SPEED_LIMIT=80");
    }

    if (!fw.audio.begin()) {
        fw.serial.writeLine("AUDIO ERROR ES8311_INIT_FAILED");
    } else {
        fw.serial.writeLine("AUDIO READY RATE=16000 FRAME=320 CODEC=ES8311");
    }

    // AudioManager owns the shared Wire bus. Touch starts afterwards and never
    // reinitializes that bus, preserving the working microphone and speaker.
    if (!fw.touch.begin()) {
        fw.serial.writeLine("TOUCH ERROR FT6336_NOT_FOUND");
    } else {
        fw.serial.writeLine("TOUCH READY SAFE_INTERRUPT_MODE");
    }

    fw.lastFrameMicros = micros();
    fw.serial.writeLine("AURA_READY");
}

void loop() {
    Firmware& fw = firmware();

    // Serial remains responsive even between graphics frames.
    // Catch up on bounded packet bursts before a microphone read or LCD
    // transfer. One command per blocking mic read throttled speaker input.
    for (uint8_t packet = 0; packet < 4; ++packet) {
        fw.serial.update();
        if (!fw.serial.available()) break;
        const char* line = fw.serial.readLine();
        if (!handleHeadServoCommand(fw, line)
                && !handleTopMotorCommand(fw, line)
                && !handleAudioCommand(fw, line)
                && !handleMusicCommand(fw, line)) {
            fw.parser.parseCommand(line);
            fw.serial.writeLine(fw.parser.lastReply());
        }
    }

    const uint32_t nowMs = millis();
    handleTouch(fw, fw.touch.update(nowMs), nowMs);
    updateTouchReaction(fw, nowMs);
    updateAngryAutoReturn(fw, nowMs);
    updateEmotionalMotor(fw);

    fw.headServo.update(nowMs);
    fw.topMotor.update(nowMs);
    if (fw.topMotor.consumeTestCompleted()) {
        fw.serial.writeLine("MOTOR TEST COMPLETE STOPPED");
    }

    streamMicrophone(fw);

    const uint32_t now = micros();
    const uint32_t elapsedUs = now - fw.lastFrameMicros;

    // Freeze the ordinary face during listening to reduce analogue microphone
    // noise. A live countdown is different: refresh it exactly once per second
    // so every displayed second advances even while wake-word capture owns the
    // microphone. This keeps SPI/display noise far below normal animation load.
    const bool microphoneActive = fw.audio.microphoneActive();
    const uint32_t faceIntervalUs =
        fw.audio.speakerActive() ? 100000UL : cfg::timing::frameUs;
    if (microphoneActive && !fw.audio.speakerActive()) {
        constexpr uint32_t kCountdownListeningRefreshUs = 1000000UL;
        const bool countdownTickDue = fw.face.countdownActive()
            && elapsedUs >= kCountdownListeningRefreshUs;
        // Transcription/generation keeps RX open for "AURA stop". Animate
        // processing dots at 10 FPS during that phase; ordinary listening
        // remains still to keep the analogue microphone quiet.
        const bool thinkingTickDue = !fw.face.countdownActive()
            && fw.face.currentEmotion() == Emotion::Thinking
            && elapsedUs >= 100000UL;
        // TIMER STOP may arrive while the continuously running wake microphone
        // owns the loop.  Permit exactly one full refresh in that case so the
        // alert artwork is erased and the neutral wake face becomes visible.
        if (fw.face.fullFrameRefreshPending() || countdownTickDue || thinkingTickDue) {
            fw.lastFrameMicros = now;
            fw.face.update(kMaxFrameMs);
        }
        yield();
        return;
    }
    if (elapsedUs >= faceIntervalUs) {
        fw.lastFrameMicros = now;

        float dtMs = static_cast<float>(elapsedUs) / 1000.0f;
        if (dtMs > kMaxFrameMs) {
            dtMs = kMaxFrameMs;
        }

        fw.face.update(dtMs);
    }

    yield();
}
