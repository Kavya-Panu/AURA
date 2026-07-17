# AURA Hardware Abstraction Layer (HAL)

The **single boundary** between AURA's software and the physical robot. The HAL
is the only module allowed to touch hardware — the ESP32, the serial port,
servos, LEDs, the propeller, battery sensors, and any future device. Every other
module (Behavior, Speech, Vision, Brain, ...) reaches hardware only by emitting
events or calling the HAL's command API; none of them import a serial library or
open a port.

**Verified:** 42 tests passing (541 across the whole project), 12× clean despite
the serial reader/writer, reconnect, and heartbeat threads. The complete robot
runs on a laptop with **no hardware** by injecting the mock transport.

## The design decision: hardware behind interfaces

Like every AURA layer, the HAL depends on **interfaces**, not devices or
libraries:

| Interface | Real | Mock (laptop/tests) |
|---|---|---|
| `SerialTransport` | `PySerialTransport` (lazy `pyserial`) | `MockSerialTransport` (in-process, scriptable, disconnectable) |
| `Device` | `SerialDevice` (driven over the ESP32 link) | `MockDevice` (battery/camera/mic/any peripheral) |

The `SerialManager` is transport-agnostic; only the injected transport opens a
port. Devices get their send path *injected* from the HardwareManager, so a
device never touches the port itself.

## Closing the loop (software → face)

This is the piece the whole project pointed toward. The Speech and Behavior
layers already emit `EMOTION_CHANGED` (with an emotion token) and mouth-shape
events. The HAL **subscribes** to them and forwards the token to the ESP32 over
serial:

```
Speech/Behavior ──EMOTION_CHANGED{"emotion":"HAPPY"}──► HAL ──"HAPPY\n"──► ESP32 face
Speech mouth    ──EMOTION_CHANGED{"mouth":"MOUTH_WIDE"}─► HAL ──"MOUTH:MOUTH_WIDE\n"─► ESP32
```

No other module knows a serial port exists.

## Components

### HardwareManager (core `Module`)
Owns the `SerialManager` and a `DeviceRegistry`, runs a heartbeat/health thread,
and is the sole hardware entry point. Responsibilities: initialize / connect /
disconnect hardware, health monitoring, send commands, receive status, device
registration + discovery, and event publishing. New hardware is added by
`register_device(...)` — **the HardwareManager itself never changes**
(Open/Closed).

### SerialManager
Owns the ESP32 link: auto-detects the COM port (by hint substrings), connects,
sends commands from a **thread-safe priority queue** on a writer thread, reads
responses on a reader thread, **auto-reconnects** when an established link drops,
and enforces timeouts. Reconnect fires only on losing a live connection — a
failed initial connect stays in `ERROR` rather than spinning.

### DeviceRegistry + Device
Thread-safe registry of devices implementing the `Device` protocol
(connect/disconnect/health_check/send_command). Supports ESP32, Servo, Speaker,
Display, Propeller, LED, Battery, Camera, Microphone, and future devices.

### device_types
`DeviceType`, `ConnectionState`, `HealthState`, and `CommandPriority`
(CRITICAL < HIGH < NORMAL < LOW — lower value sent sooner).

## Events

Publishes `HARDWARE_STARTED/STOPPED`, `DEVICE_CONNECTED/DISCONNECTED`,
`SERIAL_CONNECTED/DISCONNECTED`, `COMMAND_SENT/RECEIVED`, `DEVICE_ERROR`,
`BATTERY_LOW`, and `HARDWARE_ERROR`. Subscribes to `EMOTION_CHANGED` (to drive
the face). `BATTERY_LOW` reuses the existing core event; the other ten were added
additively.

## Threading

A serial **writer** thread (drains the priority queue), a serial **reader**
thread (dispatches inbound lines), a **reconnect** routine (on link loss), and a
**heartbeat** thread (pings the ESP32 + polls device health + checks battery).
All state is lock-guarded; verified with concurrent command bursts and 12×
flake-free runs.

## Configuration

`SerialConfig` (port or auto-detect, baud, read/write timeouts, reconnect delay,
max attempts, port hints), `QueueConfig` (max size, send timeout), `HealthConfig`
(heartbeat interval + command, battery-low threshold), and a traffic-logging
toggle.

## Usage

```python
from hardware import HardwareManager, HardwareConfig, MockDevice, DeviceType
from hardware.serial_manager import MockSerialTransport, PySerialTransport

# Laptop (no hardware):
hal = HardwareManager(bus, HardwareConfig(), MockSerialTransport(ports=["MOCK"]))

# Real robot:
hal = HardwareManager(bus, HardwareConfig(), PySerialTransport())

lifecycle.register(hal)                          # core Module; starts threads
hal.register_device(MockDevice("battery", DeviceType.BATTERY, {"percent": 95}))

hal.set_emotion("HAPPY")                         # -> ESP32 face
hal.send_command("battery", "READ")              # -> any device
hal.discover_devices()                           # {name: {type, connected, health}}
```

## Adding new hardware (no HardwareManager change)

1. Implement the `Device` protocol (or use `SerialDevice` for serial peripherals,
   `MockDevice` for in-process ones).
2. `hal.register_device(MyDevice(...))` — it connects immediately if hardware is
   running, and participates in health checks and discovery.

That's it. The HardwareManager, SerialManager, and event flow are untouched.

## Laptop setup (real serial, optional)

```bash
pip install pyserial        # only needed to talk to a real ESP32
```

Without `pyserial`, `PySerialTransport` reports unavailable and you use
`MockSerialTransport` — the whole robot still runs.

## Honest status

All logic — port auto-detection, connect/disconnect, the priority command queue,
reader/writer threads, auto-reconnect on a dropped link, the heartbeat + health
poll, battery-low detection (from telemetry or an inbound `BATTERY:<pct>` line),
device registration/discovery, `EMOTION_CHANGED → ESP32` forwarding, and every
event — is verified with the mock transport + mock devices and is stable (12×
clean). A test also asserts **no non-HAL module imports `serial`**, enforcing the
single-boundary rule. **Not** exercised here: a real `pyserial` link to a
physical ESP32 (no hardware in the sandbox). That runs the first time you inject
`PySerialTransport` on the laptop, where you'll set the port/baud (or rely on
auto-detect) — the SerialManager, devices, and every other module are unchanged.

## Two fixes made during the build (honest note)

1. **Real bug:** reconnect could fire from the reader thread even when no
   connection was ever established, flipping a failed initial connect from
   `ERROR` into a `RECONNECTING` spin. Fixed so reconnect only triggers on losing
   a live `CONNECTED` link.
2. **Test bug:** a reconnect test waited on `sm.connected`, which flips back to
   `True` so fast after reconnect that the wait returned before the cycle
   happened. Fixed to wait on the `SERIAL_DISCONNECTED` event. The serial logic
   itself was correct.

---

# HAL Stage 2 — Drivers, Router & Context

Stage 2 adds the concrete drivers that sit on top of the Stage 1 boundary. The
rule is unchanged and absolute: **every driver routes through the
HardwareManager** — no driver imports a serial library or opens a port.

```
Speech / Behavior / Brain ─► Driver ─► HardwareManager ─► SerialManager ─► ESP32
```

**Verified:** 54 new tests (96 hardware total, 595 project-wide), 12× clean. A
smoke path confirms all drivers actually write tokens to the ESP32 *through* a
real Stage 1 HardwareManager.

## The routing contract

Each driver is constructed with a `CommandSink` — a callable with the exact shape
of `HardwareManager.send_command(device, command, *, priority)`. In production you
pass `hal.send_command`; in tests/laptop you pass a `MockCommandSink` that records
commands. A driver therefore *cannot* reach hardware except via the manager, and
a test asserts none of them import `serial`.

## Drivers

| Driver | Translates to | Notes |
|---|---|---|
| `FaceDriver` | emotion tokens, `EYES:x,y`, `BLINK:n`, `MOUTH:*`, `SLEEP/WAKE`, `BOOT/SHUTDOWN` | forwards only; never renders or generates emotions |
| `ServoDriver` | `SERVO:<ch>:<angle>` | move-to, smooth (threaded, cancellable), speed, limits, calibration offset; no IK |
| `LedDriver` | `LED:<ch>:r,g,b` | brightness, color, blink/fade/pulse (threaded), idle + charging presets, RGB |
| `PropellerDriver` | `PROP:<ch>:<speed>` | start/stop, speed, timed runs, **mandatory safety timeout** |
| `BatteryMonitor` | — (consumes telemetry) | edge-triggered `BATTERY_LOW/OK/CHARGING/FULL`, voltage → health |

Every driver is thread-safe; time-based effects (smooth servo, LED effects,
timed/guarded propeller) run on their own daemon threads and are cancellable.

## CommandRouter

The dispatch layer: it validates, prioritizes, queues, de-conflicts, and cancels.
A `HardwareCommand` names a `target` and carries a `handler` (which calls a
driver). Key behaviours:

- **Priority** — CRITICAL < HIGH < NORMAL < LOW (min-heap; higher priority sent
  first).
- **Conflict prevention** — commands sharing a `conflict_key` (default = target)
  coalesce: a newer command supersedes an older queued one, so stale/conflicting
  actuator commands never both fire (e.g. two rapid `servo:pan` targets → only the
  latest runs). Set `coalesce=False` to keep every command (e.g. a blink sequence).
- **Cancellation** — `cancel(target)` or `cancel_all()`.
- **Async** — dispatch happens on a worker thread; submit never blocks.

## HardwareContext

Runtime working-state for the HAL (persists nothing): connected devices,
connection state, battery level/charging, current face emotion, servo positions,
LED state, propeller state, last command, health, and runtime statistics
(commands/errors/reconnects). `snapshot()` returns an immutable copy; a test
verifies mutating the snapshot can't affect the context.

## Mock mode

Because the Stage 1 transport is already injectable and every driver takes a
`CommandSink`, the **complete robot runs on a laptop with no hardware**: use
`MockSerialTransport` under the HardwareManager and (optionally) `MockCommandSink`
for isolated driver tests. Nothing changes when you move to real hardware except
the injected transport.

## Command flow (worked example)

```python
from hardware import (HardwareManager, HardwareConfig, MockSerialTransport,
                      FaceDriver, ServoDriver, LedDriver, PropellerDriver,
                      CommandRouter, HardwareCommand, Color)

hal = HardwareManager(bus, HardwareConfig(), MockSerialTransport(ports=["MOCK"]))
lifecycle.register(hal)

face  = FaceDriver(hal.send_command)
neck  = ServoDriver(hal.send_command, "pan")
ring  = LedDriver(hal.send_command)
prop  = PropellerDriver(hal.send_command, safety_timeout_s=30)

face.set_emotion("HAPPY")          # -> "HAPPY"        -> ESP32
neck.move_smooth(120)              # -> "SERVO:pan:.." -> ESP32 (gradual)
ring.pulse(Color(0,120,255))       # -> "LED:led:.."   -> ESP32 (breathing)

# ...or route everything through the router for priority + de-confliction:
router = CommandRouter(); router.start()
router.submit(HardwareCommand("face", lambda: face.set_emotion("EXCITED"),
                              priority=CommandPriority.HIGH))
```

## Adding new hardware

1. Write a driver that takes a `CommandSink` and translates actions into your
   device's tokens (subclass nothing — just accept `send` and call it).
2. Register a `Device` with the HardwareManager (Stage 1) so it participates in
   connection/health/discovery.
3. Optionally give the router a `conflict_key` for the new actuator.

The HardwareManager, SerialManager, and every other module stay untouched.

## Future expansion

- **Real actuators** — the token formats (`SERVO:`, `LED:`, `PROP:`) are the
  contract with the ESP32 firmware; extend the firmware parser and the driver
  together, nothing else changes.
- **Jetson** — drivers are pure command-formatters, so moving compute to a Jetson
  only swaps the transport under Stage 1.
- **RGB / animation effects** — `LedDriver` already supports full RGB and threaded
  effects; add new effect methods without touching the router or manager.

## Honest status (Stage 2)

All driver logic — token formatting, servo clamping/calibration/smooth movement,
LED brightness/color/effects, propeller safety timeout, battery edge-triggered
events, and the router's priority/coalescing/cancellation — is verified with mock
sinks and a real Stage 1 HardwareManager, and is stable (12× clean). **Not**
exercised here: the ESP32 firmware actually acting on the new `SERVO:`/`LED:`/
`PROP:` tokens (the face-emotion/`MOUTH:` tokens match the existing Face Engine;
the servo/LED/propeller tokens are new and will need matching firmware handlers).
The command *contract* is defined and tested end-to-end through the serial layer;
wiring the firmware side is the next hardware step.

### One fix during the build (honest note)

A servo cancel test injected a no-op sleep, so the "slow" smooth move finished
instantly before `cancel()` ran, making the assertion flaky-by-construction. Fixed
the test to use a real small sleep so the move is genuinely gradual and
cancellable. The servo cancellation logic itself was correct.
