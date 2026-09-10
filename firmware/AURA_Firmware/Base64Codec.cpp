#include "Base64Codec.h"

namespace aura::base64 {

namespace {
constexpr char kAlphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

int valueOf(char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    if (c == '=') return -2;
    if (c == ' ' || c == '\r' || c == '\n' || c == '\t') return -3;
    return -1;
}
}  // namespace

size_t encode(const uint8_t* input, size_t length, char* output, size_t capacity) {
    if (input == nullptr || output == nullptr) return 0;
    const size_t required = ((length + 2) / 3) * 4;
    if (capacity <= required) return 0;

    size_t in = 0;
    size_t out = 0;
    while (in < length) {
        const size_t remaining = length - in;
        const uint32_t a = input[in++];
        const uint32_t b = remaining > 1 ? input[in++] : 0;
        const uint32_t c = remaining > 2 ? input[in++] : 0;
        const uint32_t triple = (a << 16) | (b << 8) | c;

        output[out++] = kAlphabet[(triple >> 18) & 0x3F];
        output[out++] = kAlphabet[(triple >> 12) & 0x3F];
        output[out++] = remaining > 1 ? kAlphabet[(triple >> 6) & 0x3F] : '=';
        output[out++] = remaining > 2 ? kAlphabet[triple & 0x3F] : '=';
    }
    output[out] = '\0';
    return out;
}

size_t decode(const char* input, uint8_t* output, size_t capacity) {
    if (input == nullptr || output == nullptr) return 0;

    int quartet[4];
    size_t q = 0;
    size_t out = 0;
    for (const char* p = input; *p != '\0'; ++p) {
        const int value = valueOf(*p);
        if (value == -3) continue;
        if (value == -1) return 0;
        quartet[q++] = value;
        if (q != 4) continue;

        if (quartet[0] < 0 || quartet[1] < 0) return 0;
        const uint32_t triple =
            (static_cast<uint32_t>(quartet[0]) << 18) |
            (static_cast<uint32_t>(quartet[1]) << 12) |
            (static_cast<uint32_t>(quartet[2] < 0 ? 0 : quartet[2]) << 6) |
            static_cast<uint32_t>(quartet[3] < 0 ? 0 : quartet[3]);

        if (out >= capacity) return 0;
        output[out++] = static_cast<uint8_t>((triple >> 16) & 0xFF);
        if (quartet[2] != -2) {
            if (out >= capacity) return 0;
            output[out++] = static_cast<uint8_t>((triple >> 8) & 0xFF);
        }
        if (quartet[3] != -2) {
            if (out >= capacity) return 0;
            output[out++] = static_cast<uint8_t>(triple & 0xFF);
        }
        q = 0;
    }
    return q == 0 ? out : 0;
}

}  // namespace aura::base64
