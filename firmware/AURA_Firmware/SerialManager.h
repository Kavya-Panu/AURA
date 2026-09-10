// =============================================================================
//  communication/SerialManager.h
// -----------------------------------------------------------------------------
//  USB serial transport. That is its entire job.
//
//  SerialManager owns the Serial port. It reads incoming bytes non-blockingly,
//  assembles them into complete newline-terminated lines, and sends outgoing
//  text. It does NOT understand or parse commands, and it knows nothing about
//  FaceController or any face module — it just moves bytes and hands back
//  complete strings. What those strings mean is the CommandParser's problem.
//
//  Fixed-size buffers (sized from Config/Constants, not magic numbers) mean no
//  dynamic allocation ever, and an overflow-safe assembler drops over-long lines
//  rather than corrupting memory.
//
//  Allowed dependencies (and no others): Arduino.h, core/Config.h,
//  core/Constants.h.
// =============================================================================
#pragma once

#include <Arduino.h>

#include "Config.h"
#include "Constants.h"

namespace aura {

class SerialManager {
public:
    SerialManager() = default;

    // ---- lifecycle ----------------------------------------------------------

    /// Open the serial port at the given baud (defaults to the protocol baud).
    void begin(uint32_t baud = fw::serial::baudRate);

    /// Service the port: assemble at most one complete incoming line and drain
    /// pending outgoing bytes. Non-blocking; call once per loop.
    void update();

    // ---- receive ------------------------------------------------------------

    /// True when a complete line is ready to be read.
    bool available() const { return _lineReady; }

    /// Return the assembled line and mark it consumed, or nullptr if none is
    /// ready. The returned pointer is valid only until the next update()/
    /// readLine(); the caller should parse or copy it immediately.
    const char* readLine();

    // ---- transmit -----------------------------------------------------------

    /// Queue text to send (drained non-blockingly by update()). Overflow-safe:
    /// bytes that don't fit are dropped and counted, never block.
    void write(const char* text);

    /// Queue text followed by the line terminator.
    void writeLine(const char* text);

    /// Write one large line directly. Used only for real-time microphone PCM,
    /// where dropping bytes would corrupt the frame. This may wait briefly for
    /// the UART, but a 20 ms frame still fits comfortably at 921600 baud.
    void writeLineImmediate(const char* text);

    /// Best-effort, non-blocking drain of the outgoing buffer into the port.
    void flush();

    // ---- status / control ---------------------------------------------------

    /// True if the port is open and the USB host is connected.
    bool isConnected() const;

    /// Drop all buffered incoming and outgoing data.
    void clearBuffers();

    /// Count of dropped over-long RX lines + dropped TX bytes (diagnostics).
    uint32_t overflowCount() const { return _rxOverflows + _txDrops; }

private:
    void pushTx(uint8_t b);
    void drainTx();

    // Capacities live in one place (from Constants), never as scattered
    // literals.
    static constexpr size_t kRxCapacity = fw::serial::rxBufferSize;  // per line
    static constexpr size_t kTxCapacity = 512;                       // control replies

    // Receive: one line being assembled + one completed line awaiting readLine().
    char   _rxAssembly[kRxCapacity] = {};
    size_t _rxLen      = 0;
    char   _lineBuf[kRxCapacity] = {};
    bool   _lineReady  = false;
    bool   _discarding = false;      ///< dropping the rest of an over-long line

    // Transmit ring buffer.
    uint8_t _tx[kTxCapacity] = {};
    size_t  _txHead = 0, _txTail = 0, _txCount = 0;

    bool     _started    = false;
    uint32_t _rxOverflows = 0;
    uint32_t _txDrops     = 0;
};

}  // namespace aura
