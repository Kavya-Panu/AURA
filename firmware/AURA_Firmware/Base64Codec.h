#pragma once

#include <Arduino.h>

namespace aura::base64 {

/// Encode binary data. Returns characters written, excluding the NUL.
size_t encode(const uint8_t* input, size_t length, char* output, size_t capacity);

/// Decode Base64 text. Whitespace is ignored. Returns bytes written, or zero
/// for malformed input / insufficient output capacity.
size_t decode(const char* input, uint8_t* output, size_t capacity);

}  // namespace aura::base64
