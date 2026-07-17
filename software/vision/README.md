# AURA Vision System — Stage 1 (Architecture)

The skeleton of AURA's eyes. Stage 1 is **architecture only**: the coordinator,
context, config, events, result type, and exceptions that future detector stages
(face, person, phone, gesture) plug into — with **no camera access and no
detection algorithms**. It integrates with the existing Event Bus and Lifecycle
and redesigns nothing.

**Verified:** 35 vision tests passing (189 across the whole project), including
integration under the real `LifecycleManager` + `StateMachine`.

## What Stage 1 deliberately does NOT do

No OpenCV, MediaPipe, YOLO, camera capture, face/phone/person detection,
tracking, or gestures. Those arrive in later stages and slot in **without
editing `vision_manager.py`** (Open/Closed) — they only implement the `Detector`
protocol and call the manager's seams.

## Files

| File | Responsibility |
|---|---|
| `vision_manager.py` | Coordinator + core `Module`. Detector registry, lifecycle, context maintenance, event publishing, camera/result seams. **No detection logic.** |
| `vision_context.py` | Thread-safe live state; immutable `VisionSnapshot`. |
| `vision_config.py` | All configurable values (camera, processing, detector toggles) + validation. |
| `vision_events.py` | Readable `VisionEvent` names mapped onto core `RobotEvent`s. |
| `vision_result.py` | Generic `VisionResult` / `Detection` / `BoundingBox` returned by future detectors. |
| `vision_exceptions.py` | Vision errors rooted in `AuraError`. |
| `tests/` | 35 unit tests. |

## How it fits the existing architecture

```
        Future detectors (face / phone / person / gesture)  ── implement ──►┐
        (OpenCV / MediaPipe / YOLO, later stages)                           │
                                                                    Detector │ protocol
                                                                            ▼
   Future camera/processing loop ──seams──►┌──────────────────────────────────┐
     on_camera_connected()                 │          VISION MANAGER           │
     on_camera_disconnected()              │  register/unregister detectors    │
     update_metrics()                      │  lifecycle (Module)               │
     publish_result()                      │  maintains VisionContext          │
                                           │  publishes VisionEvents           │
                                           └───────────────┬──────────────────┘
                                                           │ core RobotEvents
                                                           ▼
                                                    Event Bus (core)
                                                           │
                                     Behavior / Focus / Mode managers subscribe
```

The `VisionManager` is a core `Module` (`initialize/start/stop/health_check`), so
the `LifecycleManager` owns it exactly like Voice and the others.

## VisionContext (the required state)

`enabled`, `running`, `camera_connected`, `camera_id`, `capture_fps`,
`processing_fps`, `active_detectors`, `last_error` — all lock-guarded, exposed as
an immutable `snapshot()`.

## Events

Readable `VisionEvent` names map to core `RobotEvent`s. Detection events already
existed in core from earlier layers, so they're **reused, not duplicated**; only
five lifecycle/camera events plus a generic `VISION_RESULT` were added to core
(additively).

| VisionEvent | Publishes as (core) | Emitted by |
|---|---|---|
| `VISION_STARTED` / `VISION_STOPPED` / `VISION_ERROR` | same | manager (Stage 1) |
| `CAMERA_CONNECTED` / `CAMERA_DISCONNECTED` | same | manager seams (Stage 1) |
| `VISION_RESULT` | same | `publish_result()` seam |
| `FACE_FOUND` / `FACE_LOST` | same | future detectors |
| `PHONE_DETECTED` | same | future detectors |
| `PHONE_REMOVED` | `PHONE_GONE` (alias) | future detectors |
| `PERSON_FOUND` | `PERSON_RETURNED` (alias) | future detectors |
| `PERSON_LEFT` | same | future detectors |

`PHONE_REMOVED`/`PERSON_FOUND` are the spec's names; they resolve to the
existing core `PHONE_GONE`/`PERSON_RETURNED` so subscribers written for earlier
layers keep working.

## The Detector contract (for later stages)

```python
from vision import VisionManager, VisionResult, Detection, DetectionKind

class FaceDetector:                     # Stage 2+ — implements Detector
    name = "face"
    def initialize(self): ...           # load the model
    def start(self): ...
    def stop(self): ...
    def health_check(self) -> bool: return True
    # when it processes a frame it builds a VisionResult and either
    # calls manager.publish_result(result) or emits FACE_FOUND itself

vision = VisionManager(bus, VisionConfig())
vision.register_detector(FaceDetector())   # the ONLY integration line
lifecycle.register(vision)
```

Registering a detector while the manager is already running initializes and
starts it immediately so it joins in progress.

## SOLID / design notes

- **Single Responsibility** — the manager coordinates; it never detects. Detection
  meaning lives in detectors.
- **Open/Closed** — new detectors are added via `register_detector`; the manager
  is never edited.
- **Dependency Inversion** — the manager depends on the `Detector` *protocol*,
  not on OpenCV/MediaPipe/YOLO.
- **Thread-safe** — context and registry are lock-guarded; future capture threads
  can update state and publish results safely.
- **Fail-safe** — a detector that fails to start is contained: the manager logs
  it, records `last_error`, and emits `VISION_ERROR` rather than crashing.

## Running the tests

```bash
python -m unittest discover -s vision/tests    # 35 tests, no hardware needed
```

## Next stages (not in Stage 1)

Camera backend (OpenCV capture + reconnect) → face detector (MediaPipe) →
person detector → phone detector (YOLO) → tracking → gesture. Each is a
`Detector` plugged into this manager; the Focus Manager subscribes to
`PHONE_DETECTED`/`PHONE_GONE` and `PERSON_LEFT`/`PERSON_RETURNED` for the
phone-warning and away-from-desk behaviour.

---

# Stage 2 — Camera Layer

The camera layer acquires frames and delivers them to the Vision System.
**Nothing else** — no detection, tracking, OpenCV image processing, YOLO or
MediaPipe (those are Stage 3+). It only manages cameras and moves frames.

**Verified:** 29 Stage-2 tests (64 vision total), run 15× with zero flakiness.
Modifies no existing module — it talks to Stage 1 only through duck-typed seams.

## Dependency-injected capture

`cv2.VideoCapture` isn't available everywhere, so the camera layer depends on
interfaces, not OpenCV:

| Interface | Real | Fake (tests) |
|---|---|---|
| `CaptureBackend` | `OpenCVCaptureBackend` (lazy `cv2`) | `FakeCaptureBackend` (scripted + fault injection) |
| `CameraProbe` | `OpenCVCameraProbe` | `FakeCameraProbe` (scripted device list) |

Real OpenCV is lazily imported inside the real backends, so importing this
module never requires it.

## Frame flow & threads

```
 camera ─► CaptureBackend.read() ─► camera-capture thread ─► FrameBuffer ─► detectors (Stage 3+)
                                          │ stamps + indexes      (bounded, latest-N)
                                          └─► VisionManager seams ─► Event Bus + VisionContext
```

- **One producer** (the dedicated `camera-capture` daemon thread); **many
  consumers** read concurrently.
- The capture thread **never blocks on slow consumers** — it drops old frames
  rather than waiting, so detection lag can't stall capture. The main robot
  thread is never touched.

## Buffer design

`FrameBuffer` = bounded `deque(maxlen=N)` under a lock + condition variable:
latest-only O(1) `get_latest()`, drop-oldest when full (memory bounded — proven
by a 10,000-push test), every frame timestamped, multiple concurrent consumers
(each with `since_index` to avoid reprocessing), and `wait_for_frame()` for
low-latency wakeups.

## Camera discovery, events, reconnect

`CameraSelector` + `CameraProbe` discover cameras, return `CameraInfo` metadata
(id/name/kind/backend/resolution/availability), pick a default, validate, and
switch safely. `CameraKind` covers `LAPTOP_WEBCAM`, `USB`, and `CSI` (Jetson —
via a GStreamer pipeline string on the real backend, no manager change).
`CameraManager` publishes `CAMERA_CONNECTED`/`CAMERA_DISCONNECTED` and reports
`capture_fps` through the Stage-1 seams, and auto-reconnects on read failure
(every `reconnect_interval_s`, up to `max_reconnect_attempts`, or forever).

## Usage

```python
from vision import VisionManager, VisionConfig
from vision.camera_manager import CameraManager, OpenCVCaptureBackend
from vision.camera_selector import CameraSelector, OpenCVCameraProbe
from vision.frame_buffer import FrameBuffer

vm = VisionManager(bus, VisionConfig())
selector = CameraSelector(OpenCVCameraProbe()); selector.discover()
buffer = FrameBuffer(max_frames=2)
camera = CameraManager(vm, vm.config.camera, selector, buffer,
                       OpenCVCaptureBackend())            # laptop / USB
# Jetson CSI: OpenCVCaptureBackend(pipeline="nvarguscamerasrc ! ...")
camera.open(); camera.start()
# Stage 3 detectors: buffer.wait_for_frame(since_index=last)
```

## Stage 2 files

`camera_manager.py` (capture thread, reconnect, FPS, buffer delivery,
`CaptureBackend` real/fake) · `camera_selector.py` (discovery, metadata,
selection, `CameraProbe` real/fake) · `frame_buffer.py` (thread-safe latest-N
buffer + `Frame`).

## Honest status (Stage 2)

Buffer, selector, reconnect, switching, FPS metrics, capture state machine and
all camera events are verified with fakes and race-free (15× clean). Real
`cv2.VideoCapture` capture and actual webcam/CSI behaviour are **not** tested
here — they run the first time you inject `OpenCVCaptureBackend` on the laptop;
expect to confirm `target_fps`/resolution and any CSI pipeline string then.
