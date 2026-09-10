// =============================================================================
//  communication/SerialManager.cpp
// -----------------------------------------------------------------------------
//  Implementation of the serial transport. Reads are non-blocking and bounded;
//  writes go through a fixed-size ring buffer drained as the port accepts bytes,
//  so nothing here ever blocks or allocates. Over-long incoming lines are
//  discarded safely instead of overflowing the assembly buffer.
// =============================================================================
#include "SerialManager.h"

namespace aura {

// ---- lifecycle --------------------------------------------------------------

void SerialManager::begin(uint32_t baud) {
    // HWCDC defaults to a 256-byte queue, but one 20 ms Base64 audio packet
    // is about 860 bytes. Allocate enough room before begin() so USB packet
    // bursts cannot truncate speaker or microphone frames.
    Serial.setRxBufferSize(4096);
    Serial.setTxBufferSize(4096);
    Serial.begin(baud);
    _started = true;
    clearBuffers();
}

void SerialManager::update() {
    // ---- Receive: assemble at most one line; leave the rest in the port's own
    // buffer for the next call so we never overwrite an unread line. ----
    while (!_lineReady && Serial.available() > 0) {
        const int raw = Serial.read();
        if (raw < 0) {
            break;
        }
        const char ch = static_cast<char>(raw);

        if (ch == '\r') {
            continue;                          // tolerate CRLF line endings
        }

        if (ch == fw::serial::lineEnding) {    // end of a line
            if (_discarding) {                 // it was an over-long line: drop it
                _discarding = false;
                _rxLen = 0;
                continue;
            }
            if (_rxLen == 0) {
                continue;                      // ignore blank lines (protocol noise)
            }
            for (size_t i = 0; i < _rxLen; ++i) {
                _lineBuf[i] = _rxAssembly[i];
            }
            _lineBuf[_rxLen] = '\0';
            _lineReady = true;
            _rxLen = 0;
        } else if (_discarding) {
            continue;                          // still dropping an over-long line
        } else if (_rxLen < kRxCapacity - 1) {
            _rxAssembly[_rxLen++] = ch;
        } else {
            _rxOverflows++;                    // line too long: discard to next '\n'
            _discarding = true;
            _rxLen = 0;
        }
    }

    drainTx();
}

// ---- receive ----------------------------------------------------------------

const char* SerialManager::readLine() {
    if (!_lineReady) {
        return nullptr;
    }
    _lineReady = false;
    return _lineBuf;
}

// ---- transmit ---------------------------------------------------------------

void SerialManager::write(const char* text) {
    if (text == nullptr) {
        return;
    }
    for (const char* p = text; *p != '\0'; ++p) {
        pushTx(static_cast<uint8_t>(*p));
    }
    drainTx();                                 // send immediately what fits
}

void SerialManager::writeLine(const char* text) {
    write(text);
    pushTx(static_cast<uint8_t>(fw::serial::lineEnding));
    drainTx();
}

void SerialManager::writeLineImmediate(const char* text) {
    if (!_started || text == nullptr) return;
    drainTx();
    Serial.write(reinterpret_cast<const uint8_t*>(text), strlen(text));
    Serial.write(static_cast<uint8_t>(fw::serial::lineEnding));
}

void SerialManager::flush() {
    drainTx();                                 // non-blocking best effort
}

void SerialManager::pushTx(uint8_t b) {
    if (_txCount < kTxCapacity) {
        _tx[_txHead] = b;
        _txHead = (_txHead + 1) % kTxCapacity;
        _txCount++;
    } else {
        _txDrops++;                            // buffer full: drop, never block
    }
}

void SerialManager::drainTx() {
    while (_txCount > 0 && Serial.availableForWrite() > 0) {
        Serial.write(_tx[_txTail]);
        _txTail = (_txTail + 1) % kTxCapacity;
        _txCount--;
    }
}

// ---- status / control -------------------------------------------------------

bool SerialManager::isConnected() const {
    // On the ESP32-S3 native USB CDC, `bool(Serial)` reflects whether the host
    // has opened the port. On a plain UART it is always true once begun.
    return _started && static_cast<bool>(Serial);
}

void SerialManager::clearBuffers() {
    _rxLen = 0;
    _lineReady = false;
    _discarding = false;
    _txHead = _txTail = _txCount = 0;
    while (Serial.available() > 0) {
        Serial.read();                         // drain any pending input
    }
}

}  // namespace aura
