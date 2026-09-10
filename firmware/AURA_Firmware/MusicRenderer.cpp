#include "MusicRenderer.h"

#include <cstring>

namespace aura {

namespace {
constexpr int kVideoX = 16;
constexpr int kVideoY = 12;
constexpr int kVideoW = 288;
constexpr int kVideoH = 142;
constexpr int kColumns = 16;
constexpr int kRows = 8;
constexpr int kTileW = kVideoW / kColumns;
constexpr int kTileH = kVideoH / kRows;
constexpr uint16_t kPanel = cfg::rgb565(4, 8, 18);
constexpr uint16_t kMutedText = cfg::rgb565(105, 130, 160);
constexpr uint16_t kSpotifyGreen = cfg::rgb565(30, 215, 96);
}

void MusicRenderer::begin() { reset(); }

void MusicRenderer::reset() {
    copyText(_title, sizeof(_title), "Spotify");
    copyText(_artist, sizeof(_artist), "AURA MUSIC");
    _elapsedMs = 0;
    _targetLevel = 0;
    _level = 0;
    _paused = false;
}

void MusicRenderer::update(float dtMs) {
    if (dtMs < 0.0f) dtMs = 0.0f;
    if (dtMs > 150.0f) dtMs = 150.0f;
    if (!_paused) _elapsedMs += static_cast<uint32_t>(dtMs);

    // Attack quickly and release gently so the picture remains lively between
    // the ten audio-level messages received each second.
    if (_level < _targetLevel) {
        uint8_t rise = static_cast<uint8_t>(dtMs * 0.12f);
        if (rise < 1) rise = 1;
        const uint16_t raised = static_cast<uint16_t>(_level) + rise;
        _level = (raised > _targetLevel) ? _targetLevel : static_cast<uint8_t>(raised);
    } else if (_level > _targetLevel) {
        uint8_t fall = static_cast<uint8_t>(dtMs * 0.035f);
        if (fall < 1) fall = 1;
        _level = (_level > fall) ? static_cast<uint8_t>(_level - fall) : 0;
        if (_level < _targetLevel) _level = _targetLevel;
    }
}

void MusicRenderer::render() {
    _display.clear();
    drawPixelVideo();
    drawTrackPanel();
}

void MusicRenderer::setMetadata(const char* title, const char* artist) {
    copyText(_title, sizeof(_title), title && *title ? title : "Spotify");
    copyText(_artist, sizeof(_artist), artist && *artist ? artist : "AURA MUSIC");
}

uint16_t MusicRenderer::colorWheel(uint8_t position, uint8_t brightness) {
    uint8_t r = 0;
    uint8_t g = 0;
    uint8_t b = 0;
    const uint8_t section = position / 85;
    const uint8_t offset = static_cast<uint8_t>((position % 85) * 3);
    if (section == 0) {
        r = static_cast<uint8_t>(255 - offset);
        g = offset;
    } else if (section == 1) {
        g = static_cast<uint8_t>(255 - offset);
        b = offset;
    } else {
        b = static_cast<uint8_t>(255 - offset);
        r = offset;
    }
    r = static_cast<uint8_t>((static_cast<uint16_t>(r) * brightness) / 255);
    g = static_cast<uint8_t>((static_cast<uint16_t>(g) * brightness) / 255);
    b = static_cast<uint8_t>((static_cast<uint16_t>(b) * brightness) / 255);
    return cfg::rgb565(r, g, b);
}

void MusicRenderer::copyText(char* target, size_t capacity, const char* source) {
    if (target == nullptr || capacity == 0) return;
    if (source == nullptr) source = "";
    strncpy(target, source, capacity - 1);
    target[capacity - 1] = '\0';
}

void MusicRenderer::drawPixelVideo() {
    const uint8_t phase = static_cast<uint8_t>((_elapsedMs / 14U) & 0xFFU);
    const uint8_t pulse = static_cast<uint8_t>(30 + (_level * 2));

    _display.fillRoundRect(kVideoX - 3, kVideoY - 3,
                           kVideoW + 6, kVideoH + 6, 9,
                           cfg::rgb565(12, 24, 42));

    // Deliberately chunky 16x8 raster: it reads as a tiny music video while
    // requiring no frame data over serial.
    for (int row = 0; row < kRows; ++row) {
        for (int col = 0; col < kColumns; ++col) {
            const uint8_t motion = static_cast<uint8_t>(
                phase + col * 13 - row * 17 + ((col * row) << 1));
            const int centre = 7 - abs(col - 7);
            const uint8_t energy = static_cast<uint8_t>(
                min(255, 35 + pulse / 2 + centre * 6 + row * 4));
            _display.fillRect(
                kVideoX + col * kTileW,
                kVideoY + row * kTileH,
                kTileW + 1,
                kTileH + 1,
                colorWheel(motion, energy));
        }
    }

    // Audio-reactive skyline and travelling highlight make the raster feel
    // musical rather than like a static colour test.
    for (int i = 0; i < 12; ++i) {
        const int seed = static_cast<int>((phase + i * 29) & 0x7F);
        const int height = 8 + ((_level * (18 + seed)) / 100);
        const int x = kVideoX + 12 + i * 23;
        _display.fillRoundRect(x, kVideoY + kVideoH - height - 8,
                               13, height, 3,
                               cfg::rgb565(235, 250, 255));
    }

    const int orbX = kVideoX + 20 + static_cast<int>((_elapsedMs / 18U) % 248U);
    const int orbY = kVideoY + 25 + ((_elapsedMs / 31U) % 72U);
    _display.fillCircle(orbX, orbY, 5 + _level / 22, cfg::color::catchlight);

    if (_paused) {
        _display.fillRoundRect(128, 50, 64, 64, 13, cfg::rgb565(0, 0, 0));
        _display.fillRoundRect(145, 66, 9, 32, 3, cfg::color::catchlight);
        _display.fillRoundRect(166, 66, 9, 32, 3, cfg::color::catchlight);
    }
}

void MusicRenderer::drawTrackPanel() {
    _display.fillRoundRect(12, 163, 296, 68, 11, kPanel);
    _display.fillCircle(28, 179, 8, kSpotifyGreen);
    _display.drawText(43, 171, "AURA MUSIC", kSpotifyGreen, 1);

    _display.drawText(21, 188, _title, cfg::color::catchlight, 2);
    _display.drawText(22, 210, _artist, kMutedText, 1);
    drawEqualizer();
}

void MusicRenderer::drawEqualizer() {
    const uint8_t phase = static_cast<uint8_t>(_elapsedMs / 23U);
    for (int i = 0; i < 18; ++i) {
        const uint8_t wobble = static_cast<uint8_t>((phase + i * 37) & 0x3F);
        const int height = 2 + (_level * (4 + wobble)) / 130;
        _display.fillRect(175 + i * 7, 225 - height, 4, height,
                          colorWheel(static_cast<uint8_t>(phase + i * 9), 220));
    }
}

}  // namespace aura
