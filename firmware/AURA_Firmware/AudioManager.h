#pragma once

#include <Arduino.h>
#include <AudioBoard.h>
#include <driver/i2s_std.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include "Config.h"

namespace aura {

/// ES8311 codec + ESP32 I2S transport for the LCDWIKI ES3C28P board.
/// The vendor's echo example uses paired RX/TX channels, so AURA keeps both
/// channels available. This lets the microphone hear an explicit stop command
/// while an answer is playing through the speaker.
class AudioManager {
public:
    bool begin();
    void update(float dtMs);

    bool startMicrophone();
    void stopMicrophone();
    bool microphoneActive() const { return _microphoneActive; }
    size_t readMicrophoneFrame(int16_t* mono, size_t samples);

    bool startSpeaker();
    void stopSpeaker();
    void abortSpeaker();
    bool speakerActive() const { return _speakerActive; }
    size_t playMonoPcm(const int16_t* mono, size_t samples);

    void setVolume(uint8_t percent);
    void mute();
    void unmute();

    bool isReady() const { return _ready; }
    uint32_t sampleRate() const { return cfg::hw::audio::sampleRate; }
    uint16_t frameSamples() const { return cfg::hw::audio::frameSamples; }
    uint32_t speakerFrames() const { return _speakerFrames; }
    uint32_t speakerQueueDrops() const { return _speakerQueueDrops; }
    uint32_t speakerWriteErrors() const { return _speakerWriteErrors; }
    uint32_t speakerWaits() const { return _speakerWaits; }

private:
    enum class TransportMode : uint8_t { None, FullDuplex };

    bool configureTransport(TransportMode mode);
    bool configureCodecFromVendorReference();
    bool writeCodecRegister(uint8_t reg, uint8_t value);
    bool readCodecRegister(uint8_t reg, uint8_t& value);
    void stopTransport();
    static void speakerTaskEntry(void* context);
    void speakerTaskLoop();

    struct SpeakerFrame {
        uint16_t samples = 0;
        int16_t mono[cfg::hw::audio::frameSamples] = {};
    };

    audio_driver::DriverPins _codecPins;
    audio_driver::AudioBoard _codec{
        audio_driver::AudioDriverES8311,
        _codecPins,
    };
    i2s_chan_handle_t _txChannel = nullptr;
    i2s_chan_handle_t _rxChannel = nullptr;
    TransportMode _transportMode = TransportMode::None;
    QueueHandle_t _speakerQueue = nullptr;
    TaskHandle_t _speakerTask = nullptr;
    volatile bool _speakerWriting = false;
    bool _ready = false;
    bool _microphoneActive = false;
    volatile bool _speakerActive = false;
    volatile bool _speakerEnding = false;
    volatile bool _speakerPrimed = false;
    volatile uint32_t _speakerFrames = 0;
    volatile uint32_t _speakerQueueDrops = 0;
    volatile uint32_t _speakerWriteErrors = 0;
    volatile uint32_t _speakerWaits = 0;
    bool _muted = false;
    uint8_t _volume = cfg::hw::audio::defaultVolume;
};

}  // namespace aura
