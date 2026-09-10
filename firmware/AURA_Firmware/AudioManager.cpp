#include "AudioManager.h"
#include <Driver/es8311/es8311.h>
#include <Wire.h>

namespace aura {

bool AudioManager::begin() {
    using namespace audio_driver;

    // The board shares I2C between ES8311 and touch. DriverDeviceInfo owns the
    // codec bus configuration and preserves the official 0x18 address.
    _codecPins.addI2C(
        PinFunction::CODEC,
        cfg::hw::audio::pinScl,
        cfg::hw::audio::pinSda,
        0,
        cfg::hw::audio::i2cClockHz
    );
    _codecPins.addI2S(
        PinFunction::CODEC,
        cfg::hw::audio::pinMclk,
        cfg::hw::audio::pinBck,
        cfg::hw::audio::pinLrck,
        cfg::hw::audio::pinDout,
        cfg::hw::audio::pinDin
    );
    CodecConfig codecConfig;
    codecConfig.input_device = ADC_INPUT_LINE1;
    codecConfig.output_device = DAC_OUTPUT_ALL;
    codecConfig.i2s.bits = BIT_LENGTH_16BITS;
    codecConfig.i2s.rate = RATE_16K;
    codecConfig.i2s.channels = CHANNELS2;
    codecConfig.i2s.fmt = I2S_NORMAL;
    codecConfig.i2s.mode = MODE_SLAVE;  // ESP32 supplies MCLK/BCLK/LRCK

    if (!_codec.begin(codecConfig)) {
        return false;
    }

    // Keep the amplifier silent until clocks and the codec are fully ready.
    pinMode(cfg::hw::audio::pinEnable, OUTPUT);
    digitalWrite(cfg::hw::audio::pinEnable,
                 cfg::hw::audio::enableActiveLow ? HIGH : LOW);

    // Match the manufacturer's Example_17_echo: create and enable paired RX
    // and TX channels from one I2S controller. This is required for barge-in
    // commands such as "AURA stop" while the speaker is playing.
    if (!configureTransport(TransportMode::FullDuplex)) {
        _codec.end();
        return false;
    }

    // The generic audio-driver initialisation compiles for this board but does
    // not reproduce the manufacturer's ES8311 clock/power register sequence.
    // Reapply the exact 16 kHz / 6.144 MHz configuration used by LCDWIKI's
    // working echo/music examples after MCLK is running.
    if (!configureCodecFromVendorReference()) {
        stopTransport();
        _codec.end();
        return false;
    }

    _codec.setVolume(_volume);
    _codec.setMute(false);

    // FM8002E amplifier enable is active-low on this board.
    digitalWrite(cfg::hw::audio::pinEnable,
                 cfg::hw::audio::enableActiveLow ? LOW : HIGH);

    _speakerQueue = xQueueCreate(12, sizeof(SpeakerFrame));
    if (_speakerQueue == nullptr ||
        xTaskCreatePinnedToCore(
            speakerTaskEntry,
            "aura_speaker",
            4096,
            this,
            2,
            &_speakerTask,
            0) != pdPASS) {
        stopTransport();
        _codec.end();
        return false;
    }

    _ready = true;
    return true;
}

bool AudioManager::writeCodecRegister(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(0x18);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission(true) == 0;
}

bool AudioManager::readCodecRegister(uint8_t reg, uint8_t& value) {
    Wire.beginTransmission(0x18);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(static_cast<uint8_t>(0x18),
                         static_cast<uint8_t>(1),
                         static_cast<uint8_t>(true)) != 1) {
        return false;
    }
    value = static_cast<uint8_t>(Wire.read());
    return true;
}

bool AudioManager::configureCodecFromVendorReference() {
    // Exact register sequence from the board vendor's ES8311 driver for:
    // 16 kHz, 16-bit stereo I2S, codec slave, MCLK = 16k * 384 = 6.144 MHz.
    if (!writeCodecRegister(0x00, 0x1F)) return false;
    vTaskDelay(pdMS_TO_TICKS(20));
    if (!writeCodecRegister(0x00, 0x00) ||
        !writeCodecRegister(0x00, 0x80) ||
        !writeCodecRegister(0x01, 0x3F)) {
        return false;
    }

    uint8_t reg = 0;
    if (!readCodecRegister(0x02, reg)) return false;
    reg = static_cast<uint8_t>((reg & 0x07) | 0x48);
    if (!writeCodecRegister(0x02, reg) ||
        !writeCodecRegister(0x03, 0x10) ||
        !writeCodecRegister(0x04, 0x10) ||
        !writeCodecRegister(0x05, 0x00)) {
        return false;
    }

    if (!readCodecRegister(0x06, reg)) return false;
    reg = static_cast<uint8_t>((reg & 0xE0) | 0x03);
    if (!writeCodecRegister(0x06, reg)) return false;
    if (!readCodecRegister(0x07, reg)) return false;
    reg = static_cast<uint8_t>(reg & 0xC0);
    if (!writeCodecRegister(0x07, reg) ||
        !writeCodecRegister(0x08, 0xFF)) {
        return false;
    }

    if (!readCodecRegister(0x00, reg)) return false;
    reg = static_cast<uint8_t>(reg & 0xBF);
    if (!writeCodecRegister(0x00, reg) ||
        !writeCodecRegister(0x09, 0x0C) ||
        !writeCodecRegister(0x0A, 0x0C) ||
        !writeCodecRegister(0x0D, 0x01) ||
        !writeCodecRegister(0x0E, 0x02) ||
        !writeCodecRegister(0x12, 0x00) ||
        !writeCodecRegister(0x13, 0x10) ||
        !writeCodecRegister(0x17, 0xC8) ||
        !writeCodecRegister(0x14, 0x1A) ||
        // 30 dB digital microphone gain: a practical middle point for the
        // external electret capsule. 24 dB required speaking very close to the
        // robot, while the previously tested 42 dB amplified too much noise.
        !writeCodecRegister(0x16, 0x05) ||
        !writeCodecRegister(0x1C, 0x6A) ||
        !writeCodecRegister(0x37, 0x08)) {
        return false;
    }

    // Start unmuted. The public mute/volume API controls these afterwards.
    uint8_t muteRegister = 0;
    if (!readCodecRegister(0x31, muteRegister)) return false;
    muteRegister &= static_cast<uint8_t>(~(0x40 | 0x20));
    return writeCodecRegister(0x31, muteRegister);
}

void AudioManager::update(float /*dtMs*/) {
    // I2S DMA is serviced by the ESP32 driver. Audio packets are handled by
    // explicit microphone/speaker methods from the main protocol loop.
}

bool AudioManager::startMicrophone() {
    if (!_ready) return false;
    if (!configureTransport(TransportMode::FullDuplex)) return false;
    // Silence only the DAC when this is a listening-only session. During
    // barge-in monitoring the speaker remains active and must stay audible.
    if (!_speakerActive) {
        _codec.setMute(true);
    }
    _microphoneActive = true;
    return true;
}

void AudioManager::stopMicrophone() {
    _microphoneActive = false;
}

size_t AudioManager::readMicrophoneFrame(int16_t* mono, size_t samples) {
    if (!_ready || !_microphoneActive || mono == nullptr || samples == 0) {
        return 0;
    }
    constexpr size_t kMaxSamples = cfg::hw::audio::frameSamples;
    if (samples > kMaxSamples) samples = kMaxSamples;

    int16_t stereo[kMaxSamples * 2];
    const size_t targetBytes = samples * 2 * sizeof(int16_t);
    size_t totalBytes = 0;
    const uint32_t deadline = millis() + 90;

    // ESP-IDF is allowed to return a partial DMA read even when no error is
    // reported. AURA's USB protocol, however, promises exactly 320 mono
    // samples per MIC packet. Accumulate partial DMA reads here instead of
    // emitting a shortened Base64 frame that the laptop must discard.
    while (totalBytes < targetBytes &&
           static_cast<int32_t>(deadline - millis()) > 0) {
        size_t chunkBytes = 0;
        const esp_err_t result = i2s_channel_read(
            _rxChannel,
            reinterpret_cast<uint8_t*>(stereo) + totalBytes,
            targetBytes - totalBytes,
            &chunkBytes,
            pdMS_TO_TICKS(30)
        );
        totalBytes += chunkBytes;
        if (result != ESP_OK && chunkBytes == 0) {
            vTaskDelay(pdMS_TO_TICKS(1));
        }
    }
    if (totalBytes != targetBytes) return 0;

    const size_t stereoFrames = samples;
    // ES8311 places the analogue microphone on the left slot for this board.
    // Selecting the "louder" channel independently for every packet caused
    // channel flipping and audible discontinuities that confused Whisper.
    constexpr size_t channel = 0;
    for (size_t i = 0; i < stereoFrames; ++i) {
        mono[i] = stereo[i * 2 + channel];
    }
    return stereoFrames;
}

bool AudioManager::startSpeaker() {
    if (!_ready) return false;
    if (!configureTransport(TransportMode::FullDuplex)) return false;
    xQueueReset(_speakerQueue);
    _speakerEnding = false;
    _speakerPrimed = false;
    _speakerFrames = 0;
    _speakerQueueDrops = 0;
    _speakerWriteErrors = 0;
    _speakerWaits = 0;
    _speakerActive = true;
    _codec.setMute(_muted);
    // The ES8311 driver's mute path writes DAC volume register 0x32 to zero.
    // Its unmute path only clears the mute bits and does not restore volume,
    // so startup audio worked but every answer after microphone capture was
    // silent. Reapply the remembered volume whenever playback begins.
    if (!_muted) {
        _codec.setVolume(_volume);
    }
    return true;
}

void AudioManager::stopSpeaker() {
    _speakerEnding = true; // release a short clip below the prebuffer threshold
    if (_speakerActive && _speakerQueue != nullptr) {
        const uint32_t deadline = millis() + 2500;
        while ((uxQueueMessagesWaiting(_speakerQueue) > 0 || _speakerWriting) &&
               static_cast<int32_t>(deadline - millis()) > 0) {
            vTaskDelay(pdMS_TO_TICKS(2));
        }
        // i2s_channel_write returning means data entered DMA, not that the
        // speaker has played it. Drain the explicitly configured 120 ms DMA
        // ring before muting, so sentence endings are not cut off.
        vTaskDelay(pdMS_TO_TICKS(140));
    }
    _speakerActive = false;
    _codec.setMute(true);
}

void AudioManager::abortSpeaker() {
    // Barge-in must be immediate: discard queued frames and mute the DAC
    // instead of waiting for the normal graceful queue drain.
    _speakerActive = false;
    _speakerEnding = false;
    _speakerPrimed = false;
    if (_speakerQueue != nullptr) {
        xQueueReset(_speakerQueue);
    }
    _codec.setMute(true);
}

size_t AudioManager::playMonoPcm(const int16_t* mono, size_t samples) {
    if (!_ready || !_speakerActive || _muted || mono == nullptr || samples == 0) {
        return 0;
    }

    constexpr size_t kMaxSamples = cfg::hw::audio::frameSamples;
    if (samples > kMaxSamples) samples = kMaxSamples;

    SpeakerFrame frame;
    frame.samples = static_cast<uint16_t>(samples);
    memcpy(frame.mono, mono, samples * sizeof(int16_t));
    if (xQueueSend(_speakerQueue, &frame, pdMS_TO_TICKS(120)) != pdTRUE) {
        ++_speakerQueueDrops;
        return 0;
    }
    ++_speakerFrames;
    return samples;
}

void AudioManager::setVolume(uint8_t percent) {
    if (percent > 100) percent = 100;
    _volume = percent;
    if (_ready) _codec.setVolume(_volume);
}

void AudioManager::mute() {
    _muted = true;
    if (_ready) _codec.setMute(true);
}

void AudioManager::unmute() {
    _muted = false;
    if (_ready && _speakerActive) {
        _codec.setMute(false);
        // Restore register 0x32, which the ES8311 mute routine zeroes.
        _codec.setVolume(_volume);
    }
}

bool AudioManager::configureTransport(TransportMode mode) {
    if (_transportMode == mode) return true;
    stopTransport();
    if (mode == TransportMode::None) return true;

    i2s_chan_config_t channelConfig =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    channelConfig.auto_clear = true;
    channelConfig.dma_desc_num = 6;
    channelConfig.dma_frame_num = cfg::hw::audio::frameSamples;

    // The LCDWIKI vendor echo demo creates both handles in one call. Using
    // exactly that paired-channel pattern avoids clocks being torn down when
    // AURA switches between listening, speaking and simultaneous barge-in.
    esp_err_t result = i2s_new_channel(
        &channelConfig,
        &_txChannel,
        &_rxChannel
    );
    if (result != ESP_OK) {
        stopTransport();
        return false;
    }

    i2s_std_config_t streamConfig = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(cfg::hw::audio::sampleRate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = static_cast<gpio_num_t>(cfg::hw::audio::pinMclk),
            .bclk = static_cast<gpio_num_t>(cfg::hw::audio::pinBck),
            .ws = static_cast<gpio_num_t>(cfg::hw::audio::pinLrck),
            .dout = static_cast<gpio_num_t>(cfg::hw::audio::pinDout),
            .din = static_cast<gpio_num_t>(cfg::hw::audio::pinDin),
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    // Match the ES3C28P manufacturer's ES8311 reference design. The board's
    // speaker DAC/amp path is silent when this codec is clocked with the
    // generic 256x profile used by the third-party driver.
    streamConfig.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_384;

    if (i2s_channel_init_std_mode(_txChannel, &streamConfig) != ESP_OK ||
        i2s_channel_init_std_mode(_rxChannel, &streamConfig) != ESP_OK ||
        i2s_channel_enable(_txChannel) != ESP_OK ||
        i2s_channel_enable(_rxChannel) != ESP_OK) {
        stopTransport();
        return false;
    }

    _transportMode = mode;
    return true;
}

void AudioManager::stopTransport() {
    if (_txChannel != nullptr) {
        i2s_channel_disable(_txChannel);
        i2s_del_channel(_txChannel);
        _txChannel = nullptr;
    }
    if (_rxChannel != nullptr) {
        i2s_channel_disable(_rxChannel);
        i2s_del_channel(_rxChannel);
        _rxChannel = nullptr;
    }
    _transportMode = TransportMode::None;
}

void AudioManager::speakerTaskEntry(void* context) {
    static_cast<AudioManager*>(context)->speakerTaskLoop();
}

void AudioManager::speakerTaskLoop() {
    SpeakerFrame frame;
    int16_t stereo[cfg::hw::audio::frameSamples * 2];

    for (;;) {
        if (!_speakerActive) {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }
        // Build a 60 ms lead before consuming a new stream. This absorbs
        // ordinary Windows/USB scheduling jitter without long barge-in lag.
        if (!_speakerPrimed) {
            if (uxQueueMessagesWaiting(_speakerQueue) < 3 && !_speakerEnding) {
                vTaskDelay(pdMS_TO_TICKS(2));
                continue;
            }
            _speakerPrimed = true;
        }
        if (xQueueReceive(_speakerQueue, &frame, pdMS_TO_TICKS(40)) != pdTRUE) {
            if (_speakerActive && !_speakerEnding) ++_speakerWaits;
            continue;
        }
        if (!_speakerActive || _txChannel == nullptr || frame.samples == 0) {
            continue;
        }

        for (size_t i = 0; i < frame.samples; ++i) {
            stereo[i * 2] = frame.mono[i];
            stereo[i * 2 + 1] = frame.mono[i];
        }

        _speakerWriting = true;
        const size_t totalBytes = frame.samples * 2 * sizeof(int16_t);
        size_t offset = 0;
        while (_speakerActive && offset < totalBytes) {
            size_t bytesWritten = 0;
            const esp_err_t result = i2s_channel_write(
                _txChannel, reinterpret_cast<const uint8_t*>(stereo) + offset,
                totalBytes - offset, &bytesWritten, 80); // API uses milliseconds
            offset += bytesWritten;
            if (result != ESP_OK || bytesWritten == 0) {
                ++_speakerWriteErrors;
                if (bytesWritten == 0) break;
            }
        }
        _speakerWriting = false;
    }
}

}  // namespace aura
