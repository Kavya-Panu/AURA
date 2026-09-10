"""
run_aura_brain.py
=================
First real end-to-end AURA integration:

    keyboard question
        -> EventBus QUESTION_RECEIVED
        -> BrainManager
        -> local Ollama / Qwen 3
        -> ANSWER_READY
        -> BrainHardwareBridge chooses expression
        -> HardwareManager
        -> USB serial
        -> ESP32 face

This stage supports both typed and push-to-talk microphone questions. Local
Whisper converts speech from the robot's onboard microphone, Qwen generates the
answer, and pyttsx3 returns speech through the robot's ES8311 speaker while the
ESP32 displays the appropriate expression.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from brain import (
    BrainConfig, BrainManager, ProviderConfig, SelectionRules, TaskKind,
    WeatherService, WebSearchService,
)
from brain.provider_registry import MockProvider, OllamaProvider
from brain.focus_service import FocusStudyService
from brain.reminder_service import ReminderService, ScheduledAlert
from core.constants import RobotEvent
from core.event_bus import Event, EventBus
from core.lifecycle import LifecycleManager
from core.logger import configure_logging, get_logger
from core.config import LoggingConfig
from core.state_machine import build_aura_state_machine
from hardware import (
    CommandPriority,
    HardwareConfig,
    HardwareManager,
    HealthConfig,
    MockSerialTransport,
    PySerialTransport,
    QueueConfig,
    SerialConfig,
)
from integration import BrainHardwareBridge
from music import MusicController
from speech import AudioPlayer, RealAudioSink, SpeechConfig, SpeechManager, TTSManager
from speech.audio_player import Esp32AudioSink
from speech.tts_manager import Pyttsx3Engine
from voice.backends import Esp32SerialMicrophone, SoundDeviceMicrophone
from voice.push_to_talk import PushToTalkListener
from voice.listening_modes import is_stop_phrase
from voice.vosk_wake_listener import VoskWakeWordListener
from voice.wake_handoff import acknowledge_wake
from voice.voice_exceptions import MicrophoneError
from voice.voice_config import (
    AudioConfig,
    MicrophoneConfig,
    NoiseConfig,
    STTConfig,
    VADConfig,
    VoiceConfig,
)
from vision.face_follower import FaceFollower, OpenCVHaarFaceBackend
from vision.face_recognizer import SFaceRecognizer
from vision.google_lens import GoogleLensService
from vision.object_vision import ObjectVisionService
from vision.focus_distraction import (
    FocusDistractionConfig,
    FocusDistractionMonitor,
)
from hardware.esp32_protocol import (
    timer_alert_command,
    timer_start_command,
    timer_stop_command,
)

log = get_logger("run_aura_brain")

ROOT = Path(__file__).resolve().parent
DEFAULT_SETTINGS = ROOT / "aura_settings.json"

# Keep the finished timer artwork visible briefly after the spoken alert, then
# return the display to AURA's neutral wake face.  This is deliberately handled
# by the laptop rather than a blocking delay in the ESP32 render loop, so touch,
# microphone, and serial processing remain responsive throughout the alert.
TIMER_ALERT_SCREEN_HOLD_S = 3.0


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid settings JSON: {path}\n{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Settings file must contain a JSON object: {path}")
    return value


def parse_args() -> argparse.Namespace:
    settings_path = Path(os.getenv("AURA_SETTINGS", DEFAULT_SETTINGS))
    settings = load_settings(settings_path)

    parser = argparse.ArgumentParser(
        description="Run AURA's local Qwen brain connected to the ESP32 face."
    )
    parser.add_argument(
        "--port",
        default=os.getenv("AURA_SERIAL_PORT", settings.get("serial_port")),
        help="ESP32 serial port, e.g. COM14. Leave empty for auto-detection.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("AURA_OLLAMA_MODEL",
                          settings.get("ollama_model", "qwen3.5:4b")),
        help="Ollama model name. Default: qwen3.5:4b",
    )
    parser.add_argument(
        "--mode",
        default=settings.get("mode", "ASSISTANT"),
        help="Initial brain mode, e.g. ASSISTANT or TEACHER.",
    )
    parser.add_argument(
        "--mock-brain",
        action="store_true",
        help="Use a deterministic mock brain instead of Ollama.",
    )
    parser.add_argument(
        "--mock-hardware",
        action="store_true",
        help="Use a mock ESP32 transport instead of a physical COM port.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=bool(settings.get("debug", False)),
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Disable microphone input and spoken answers.",
    )
    parser.add_argument(
        "--mic",
        type=int,
        default=settings.get("microphone_index"),
        help="sounddevice input-device index. Default: system microphone.",
    )
    parser.add_argument(
        "--whisper-model",
        default=settings.get("whisper_model", "distil-large-v3"),
        help="faster-whisper model. Default: distil-large-v3.",
    )
    parser.add_argument(
        "--whisper-device",
        default=settings.get("whisper_device", "cpu"),
        choices=("cpu", "cuda", "auto"),
        help="Where Whisper runs. CPU avoids competing with Qwen for GPU VRAM.",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Keep microphone input but disable spoken answers.",
    )
    parser.add_argument(
        "--voice-mode",
        choices=("push", "conversation", "wake"),
        default=settings.get("voice_mode", "push"),
        help="push, conversation, or proper offline Hey AURA wake mode.",
    )
    parser.add_argument(
        "--wake-model",
        default=settings.get(
            "wake_word_model",
            "models/vosk-model-small-en-us-0.15",
        ),
        help="Path to the lightweight Vosk wake-word model.",
    )
    parser.add_argument(
        "--audio-io",
        choices=("esp32", "laptop"),
        default=settings.get("audio_io", "esp32"),
        help="Use the robot's onboard ES8311 audio or the laptop audio devices.",
    )
    parser.add_argument(
        "--speaker-volume",
        type=int,
        default=int(settings.get("speaker_volume", 68)),
        help="Robot speaker volume from 0 to 100.",
    )
    parser.add_argument(
        "--face-tracking",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("face_tracking_enabled", True)),
        help="Track the largest face with the laptop webcam.",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=int(settings.get("camera_index", 0)),
        help="OpenCV camera index. Default: 0.",
    )
    parser.add_argument(
        "--camera-mirror",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("camera_mirror_x", False)),
        help="Reverse horizontal face-following direction if needed.",
    )
    parser.add_argument(
        "--camera-preview",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("camera_preview_enabled", True)),
        help="Show the live face-detection camera window.",
    )
    parser.add_argument(
        "--head-servo-reverse",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("head_servo_reverse", False)),
        help="Reverse the GPIO21 head-servo tracking direction.",
    )
    parser.add_argument(
        "--head-servo-range",
        type=float,
        default=float(settings.get("head_servo_range_deg", 60.0)),
        help="Head travel on either side of centre, in degrees.",
    )
    parser.add_argument(
        "--head-servo-center",
        type=float,
        default=float(settings.get("head_servo_center_deg", 95.0)),
        help="Calibrated physical head-centre angle in degrees.",
    )
    parser.add_argument(
        "--face-recognition",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("face_recognition_enabled", True)),
        help="Recognise locally enrolled faces using OpenCV SFace.",
    )
    parser.add_argument(
        "--face-recognition-threshold",
        type=float,
        default=float(settings.get("face_recognition_threshold", 0.40)),
        help="Cosine threshold for recognising a saved face.",
    )
    parser.add_argument(
        "--face-greeting-cooldown",
        type=float,
        default=float(settings.get("face_greeting_cooldown_s", 300.0)),
        help="Seconds before greeting the same recognised person again.",
    )
    parser.add_argument(
        "--face-owner-name",
        default=str(settings.get("face_owner_name", "Kavya")),
        help="Name used by the spoken 'learn my face' command.",
    )
    parser.add_argument(
        "--object-vision",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("object_vision_enabled", True)),
        help="Answer visual questions using the camera and local object detection.",
    )
    parser.add_argument(
        "--focus-distraction",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("focus_distraction_enabled", True)),
        help="Warn about a persistent visible phone or prolonged absence in focus mode.",
    )
    parser.add_argument(
        "--focus-phone-seconds",
        type=float,
        default=float(settings.get("focus_phone_persist_s", 4.0)),
        help="Seconds a phone must remain visible before a focus warning.",
    )
    parser.add_argument(
        "--focus-absence-seconds",
        type=float,
        default=float(settings.get("focus_absence_persist_s", 30.0)),
        help="Seconds without a visible face before a focus warning.",
    )
    parser.add_argument(
        "--focus-warning-cooldown",
        type=float,
        default=float(settings.get("focus_warning_cooldown_s", 90.0)),
        help="Minimum seconds between repeated warnings of the same kind.",
    )
    parser.add_argument(
        "--google-lens",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("google_lens_enabled", True)),
        help="Use Google Web Detection for Lens-style image searches.",
    )
    parser.add_argument(
        "--google-vision-credentials",
        default=str(settings.get("google_vision_credentials", "")),
        help="Path to a Google Cloud service-account JSON credential file.",
    )
    parser.add_argument(
        "--google-lens-results",
        type=int,
        default=int(settings.get("google_lens_max_results", 10)),
        help="Maximum Google Web Detection results requested per image.",
    )
    parser.add_argument(
        "--weather-location",
        default=str(settings.get("weather_location", "Liverpool")),
        help="Default city for weather questions that do not name a place.",
    )
    parser.add_argument(
        "--weather-country-code",
        default=str(settings.get("weather_country_code", "GB")),
        help="Two-letter country code used to disambiguate the default city.",
    )
    parser.add_argument(
        "--web-search",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("web_search_enabled", True)),
        help="Automatically search the web for current information.",
    )
    parser.add_argument(
        "--web-search-results",
        type=int,
        default=int(settings.get("web_search_results", 4)),
        help="Number of web results supplied to the local brain.",
    )
    parser.add_argument(
        "--music",
        action=argparse.BooleanOptionalAction,
        default=bool(settings.get("music_enabled", True)),
        help="Enable Spotify Desktop control and the ESP32 visualizer.",
    )
    parser.add_argument(
        "--music-capture-device",
        default=str(settings.get("music_capture_device", "")),
        help="Windows output to relay; empty uses the default output.",
    )
    return parser.parse_args()


def build_brain_config(model: str) -> tuple[BrainConfig, ProviderConfig]:
    provider = ProviderConfig(
        name="ollama",
        model=model,
        priority=1,
        max_retries=1,
        is_local=True,
        enabled=True,
        temperature=0.30,
        max_tokens=96,
    )

    one_provider = ["ollama"]
    rules = SelectionRules(
        by_task={task.value: one_provider for task in TaskKind},
        default_chain=one_provider,
        prefer_local_when_offline=True,
    )

    return (
        BrainConfig(
            providers=[provider],
            selection=rules,
            max_history_turns=4,
            request_timeout_s=60.0,
            enable_cache=True,
            cache_size=128,
            default_temperature=0.30,
        ),
        provider,
    )


def build_hardware_config(port: str | None) -> HardwareConfig:
    return HardwareConfig(
        serial=SerialConfig(
            port=port or None,
            baud_rate=921600,
            read_timeout_s=0.1,
            write_timeout_s=1.0,
            reconnect_delay_s=2.0,
            max_reconnect_attempts=0,
        ),
        queue=QueueConfig(max_size=256, send_timeout_s=1.0),
        health=HealthConfig(
            enabled=True,
            interval_s=5.0,
            heartbeat_command="PING",
            battery_low_threshold=20.0,
        ),
        log_traffic=False,
    )


def wait_for_serial(hardware: HardwareManager, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if hardware.serial_state.name == "CONNECTED":
            return True
        time.sleep(0.05)
    return False


def print_help() -> None:
    print(
        "\nCommands:\n"
        "  [press Enter]       Record one spoken question\n"
        "  /listen             Record one spoken question\n"
        "  /mics               List available microphone devices\n"
        "  /audio              Check the onboard ES8311 audio link\n"
        "  /speaker-test       Play a clear robot-speaker test message\n"
        "  /volume 70          Set robot speaker volume (0..100)\n"
        "  /music              Show Spotify music status\n"
        "  /play song name     Play a Spotify search result\n"
        "  /pause              Pause Spotify\n"
        "  /resume             Resume Spotify\n"
        "  /next               Play the next Spotify track\n"
        "  /previous           Play the previous Spotify track\n"
        "  /music stop         Stop music mode\n"
        "  /calibrate          Recalibrate for current room noise\n"
        "  /conversation       Hands-free follow-up conversation\n"
        "  /wake               Respond only after hearing 'AURA'\n"
        "  /say hello          Test AURA's speaker voice\n"
        "  /stop               Stop the current spoken answer\n"
        "  /emotion HAPPY      Set a face directly\n"
        "  /blink              Blink once\n"
        "  /focus on           Start a 25-minute study session\n"
        "  /focus 40           Start a 40-minute study session\n"
        "  /focus pause        Pause the study session\n"
        "  /focus resume       Resume the study session\n"
        "  /focus status       Show remaining focus time\n"
        "  /focus off          End the study session\n"
        "  /status             Ask ESP32 for status\n"
        "  /vision             Show face-tracking status\n"
        "  /see                Describe what the camera can see\n"
        "  /lens               Search the current camera image on the web\n"
        "  /timers             Show active timers and reminders\n"
        "  /cancel timers      Cancel all timers, alarms and reminders\n"
        "  /enroll Kavya       Learn and save a face locally\n"
        "  /faces              List enrolled people\n"
        "  /forget Kavya       Delete one saved face profile\n"
        "  /mode TEACHER       Change brain prompt mode\n"
        "  /quit               Shut down AURA\n"
        "  Any other text is sent to the local Qwen brain.\n"
    )


def main() -> int:
    args = parse_args()

    logging_cfg = LoggingConfig(
        debug=args.debug,
        file_enabled=True,
        directory="logs",
        filename="aura_brain.log",
    )
    configure_logging(logging_cfg)

    bus = EventBus()
    machine = build_aura_state_machine(bus)
    lifecycle = LifecycleManager(bus, machine)

    transport = (
        MockSerialTransport(
            ports=["MOCK-ESP32"],
            responder=lambda line: ["PONG"] if line == "PING" else ["OK"],
        )
        if args.mock_hardware
        else PySerialTransport()
    )
    hardware = HardwareManager(
        bus,
        build_hardware_config(args.port),
        transport,
    )
    music = MusicController(
        hardware,
        enabled=args.music,
        capture_device=args.music_capture_device,
    )
    brain_cfg, ollama_cfg = build_brain_config(args.model)
    weather = WeatherService(
        default_location=args.weather_location,
        default_country_code=args.weather_country_code,
    )
    web_search = (
        WebSearchService(max_results=args.web_search_results)
        if args.web_search
        else None
    )
    brain = BrainManager(
        bus,
        brain_cfg,
        weather_service=weather,
        web_search_service=web_search,
    )

    if args.mock_brain:
        brain.register_provider(
            MockProvider(
                "ollama",
                is_local=True,
                responder=lambda req: (
                    "Hello! The mock AURA brain received: "
                    + (req.messages[-1]["content"] if req.messages else "")
                ),
            )
        )
    else:
        brain.register_provider(OllamaProvider(ollama_cfg))

    bridge = BrainHardwareBridge(bus)

    voice_enabled = not args.no_voice
    listener = None
    wake_listener = None
    speech = None

    def recognition_status(message: str) -> None:
        print(f"[RECOGNITION] {message}")
        match = re.fullmatch(r"Face profile saved for (.+)\.", message)
        if match and speech is not None:
            learned_name = match.group(1)
            speech.say(
                f"I have learned your face, {learned_name}.",
                emotion_hint="HAPPY",
                priority=20,
            )

    def on_face_recognized(name: str, score: float) -> None:
        print(f"[RECOGNITION] Hello {name} ({score:.0%} match)")
        hardware.set_emotion("HAPPY")
        if speech is not None and not hardware.audio_link.speaker_active:
            speech.say(
                f"Hello {name}.",
                emotion_hint="HAPPY",
                priority=25,
            )

    # Face tracking and ESP32 audio share one USB serial connection.  Keep
    # tracking active while waiting for the wake word, but temporarily stop
    # sending gaze commands while recording the actual question.  This gives
    # microphone PCM frames priority at the most important moment.
    voice_capture_active = threading.Event()
    assistant_busy = threading.Event()

    face_follower = None
    if args.face_tracking:
        recognizer = None
        if args.face_recognition:
            recognizer = SFaceRecognizer(
                ROOT / "models" / "face_recognition_sface_2021dec.onnx",
                ROOT / "data" / "faces" / "face_templates.json",
                threshold=args.face_recognition_threshold,
                greeting_cooldown_s=args.face_greeting_cooldown,
                status=recognition_status,
                on_recognized=on_face_recognized,
            )
        face_follower = FaceFollower(
            OpenCVHaarFaceBackend(
                camera_index=args.camera_index,
                show_preview=args.camera_preview,
                recognizer=recognizer,
            ),
            send_gaze=lambda x, y: hardware.send_face_command(
                f"GAZE {x:.3f} {y:.3f}",
                priority=CommandPriority.LOW,
            ),
            send_head=lambda angle: hardware.send_face_command(
                f"SERVO:HEAD:{angle:.1f}",
                priority=CommandPriority.LOW,
            ),
            pause_when=lambda: (
                hardware.audio_link.speaker_active
                or voice_capture_active.is_set()
            ),
            status=lambda message: print(f"[VISION] {message}"),
            mirror_x=args.camera_mirror,
            head_reverse=args.head_servo_reverse,
            head_range_deg=args.head_servo_range,
            head_center_deg=args.head_servo_center,
        )

    # Reuse the face-tracking camera instead of opening a second camera.
    # The detector itself is loaded lazily and only runs when AURA receives a
    # visual question, so normal face tracking and voice response stay fast.
    object_vision = (
        ObjectVisionService(ROOT / "models")
        if args.object_vision
        else None
    )
    lens_credentials = str(args.google_vision_credentials or "").strip()
    if lens_credentials:
        credential_path = Path(os.path.expandvars(lens_credentials)).expanduser()
        if not credential_path.is_absolute():
            credential_path = ROOT / credential_path
        lens_credentials = str(credential_path.resolve())
    google_lens = (
        GoogleLensService(
            lens_credentials or None,
            max_results=args.google_lens_results,
        )
        if args.google_lens
        else None
    )

    if voice_enabled:
        voice_cfg = VoiceConfig(
            audio=AudioConfig(
                sample_rate=16_000,
                channels=1,
                frame_ms=20,
                dtype="int16",
            ),
            vad=VADConfig(
                aggressiveness=0,
                start_frames=3,
                # Adaptive Siri-like endpointing: short answers get a little
                # thinking room; sustained speech ends more quickly once the
                # user actually stops.
                silence_timeout_s=0.90,
                short_silence_timeout_s=1.15,
                long_silence_timeout_s=0.75,
                max_utterance_s=10.0,
                pre_roll_ms=500,
                calibration_s=1.5,
                wait_for_speech_s=12.0,
                min_speech_s=0.30,
                noise_multiplier=1.05,
                noise_margin=0.00010,
            ),
            stt=STTConfig(
                model_size=args.whisper_model,
                device=args.whisper_device,
                # RTX 4050 profile: quantized weights minimize VRAM while
                # float16 CUDA kernels make transcription much faster.
                compute_type=(
                    "int8_float16" if args.whisper_device == "cuda" else "int8"
                ),
                # Beam 3 is the tested balance for Kavya's pronunciation:
                # more accurate than the fast medium/beam-2 configuration
                # without returning to the slower beam-5 decoder.
                beam_size=3,
                best_of=3,
                language="en",
                # Keep normal questions permissive. Follow-up echo is rejected
                # separately, so accented speech is not discarded globally.
                min_confidence=0.20,
            ),
            noise=NoiseConfig(
                enabled=True,
                sensitivity=0.25,
                high_pass_hz=80,
                auto_gain=True,
                target_rms=0.10,
                max_gain=12.0,
                peak_limit=0.92,
            ),
            microphone=MicrophoneConfig(
                device_index=args.mic,
                reconnect_interval_s=0.5,
                max_reconnect_attempts=1,
            ),
            require_wake_word=False,
            default_language="en",
        )
        microphone = (
            Esp32SerialMicrophone(hardware.audio_link)
            if args.audio_io == "esp32"
            else SoundDeviceMicrophone(voice_cfg.audio, args.mic)
        )
        def voice_status(message: str) -> None:
            print(f"[VOICE] {message}")
            # Recording has ended and Whisper is about to start. Enter the
            # processing animation here—not later when Qwen receives text.
            if message.strip().lower() == "transcribing...":
                hardware.set_emotion("THINKING")

        listener = PushToTalkListener(
            voice_cfg,
            status=voice_status,
            microphone=microphone,
            play_cue=args.audio_io == "laptop",
        )
        if args.voice_mode == "wake":
            wake_model = Path(args.wake_model)
            if not wake_model.is_absolute():
                wake_model = ROOT / wake_model
            wake_listener = VoskWakeWordListener(
                voice_cfg.audio,
                microphone,
                wake_model,
                status=lambda message: print(f"[WAKE] {message}"),
            )

        if not args.no_tts:
            speech_cfg = SpeechConfig(
                default_profile="friendly",
                default_engine="pyttsx3",
                max_queue=8,
                # Current ESP32 firmware does not expose viseme commands yet.
                enable_mouth_animation=False,
                enable_expressions=True,
            )
            sink = (
                Esp32AudioSink(hardware.audio_link)
                if args.audio_io == "esp32"
                else RealAudioSink()
            )
            speech = SpeechManager(
                bus,
                speech_cfg,
                TTSManager([Pyttsx3Engine()], preferred="pyttsx3"),
                AudioPlayer(sink),
            )

    lifecycle.register(hardware)
    lifecycle.register(music)
    lifecycle.register(brain)
    lifecycle.register(bridge)
    if face_follower is not None:
        lifecycle.register(face_follower)
    if listener is not None:
        lifecycle.register(listener)
    if wake_listener is not None:
        lifecycle.register(wake_listener)
    if speech is not None:
        lifecycle.register(speech)

    answer_lock = threading.RLock()
    last_answer: dict[str, object] = {}
    answer_ready = threading.Event()
    speech_started = threading.Event()
    speech_finished = threading.Event()
    cancelled_requests: set[str] = set()
    cancelled_requests_lock = threading.RLock()

    def on_answer(event: Event) -> None:
        data = event.data or {}
        request_id = str(data.get("request_id") or "")
        if request_id:
            with cancelled_requests_lock:
                if request_id in cancelled_requests:
                    cancelled_requests.discard(request_id)
                    return
        with answer_lock:
            last_answer.clear()
            last_answer.update(data)
        if data.get("success", False):
            elapsed = data.get("processing_time")
            suffix = f"  [{elapsed}s]" if elapsed is not None else ""
            print(f"\nAURA: {data.get('text', '')}{suffix}\n")
            metadata = data.get("metadata") or {}
            sources = metadata.get("sources") or []
            if sources:
                print("[WEB] Sources:")
                for index, source in enumerate(sources, start=1):
                    print(
                        f"  {index}. {source.get('title', 'Source')}\n"
                        f"     {source.get('url', '')}"
                    )
                print()
            # Keep the processing animation visible while TTS prepares the
            # answer. BrainHardwareBridge may choose a content emotion when
            # the text arrives, but the user asked for THINKING until actual
            # speaker playback begins.
            hardware.set_emotion("THINKING")
        else:
            print("\nAURA brain error: no response was generated.\n")
        answer_ready.set()

    bus.subscribe(RobotEvent.ANSWER_READY, on_answer, priority=10)

    def on_speech_started(_event: Event) -> None:
        # AURA smiles for the entire spoken response.
        hardware.set_emotion("HAPPY")
        speech_finished.clear()
        speech_started.set()

    def on_tts_started(_event: Event) -> None:
        # SpeechManager may select a content-specific expression immediately
        # before synthesis. Override it so THINKING remains uninterrupted
        # while the voice is being prepared.
        hardware.set_emotion("THINKING")

    def on_speech_finished(_event: Event) -> None:
        # Keep the smile visible as the five-second conversation window opens.
        hardware.set_emotion("HAPPY")
        speech_finished.set()

    bus.subscribe(RobotEvent.TTS_STARTED, on_tts_started, priority=10)
    bus.subscribe(RobotEvent.SPEECH_STARTED, on_speech_started, priority=10)
    bus.subscribe(RobotEvent.SPEECH_FINISHED, on_speech_finished, priority=10)
    bus.subscribe(RobotEvent.SPEECH_CANCELLED, on_speech_finished, priority=10)

    pong = threading.Event()

    def on_serial(event: Event) -> None:
        line = str((event.data or {}).get("line") or "")
        if args.debug:
            print(f"[ESP32] {line}")
        if line == "PONG":
            pong.set()

    bus.subscribe(RobotEvent.COMMAND_RECEIVED, on_serial, priority=10)

    mode = str(args.mode).upper()
    focus_previous_mode = mode

    reminders: ReminderService | None = None
    focus: FocusStudyService | None = None
    focus_monitor: FocusDistractionMonitor | None = None

    try:
        with lifecycle:
            if not wait_for_serial(hardware):
                ports = hardware.available_ports()
                print("\nESP32 serial connection failed.")
                print(f"Requested port: {args.port or 'auto-detect'}")
                print(f"Detected ports: {ports or 'none'}")
                print("Close Arduino Serial Monitor, confirm the COM port, then run:")
                print("  python run_aura_brain.py --port COM14")
                return 2

            # Give the ESP32 time to complete the USB reset caused by opening COM.
            time.sleep(1.0)
            hardware.send_face_command("PING", priority=CommandPriority.CRITICAL)
            if pong.wait(timeout=2.0):
                print("ESP32 face link: CONNECTED (PONG received)")
            else:
                print("ESP32 face link: serial opened, but no PONG was received.")
                print("Close Arduino Serial Monitor if it is still open.")

            if args.audio_io == "esp32":
                if hardware.audio_link.probe(timeout_s=3.0):
                    print("ESP32 audio: READY (ES8311 microphone + speaker)")
                    hardware.audio_link.set_volume(
                        max(0, min(100, args.speaker_volume))
                    )
                    hardware.audio_link.unmute()
                else:
                    print("ESP32 audio: NOT READY")
                    detail = hardware.audio_link.last_error
                    if detail:
                        print(f"  {detail}")
                    print("The face can still work, but onboard voice is unavailable.")

            hardware.set_emotion("NORMAL")
            hardware.send_face_command(
                "MOTOR:TOP:QUIET:OFF", priority=CommandPriority.HIGH,
            )
            print(
                "Spotify visualizer: "
                + ("READY" if args.music else "OFF")
            )

            if not args.mock_brain:
                print(f"Warming Ollama model {args.model}...")
                try:
                    import ollama
                    ollama.chat(
                        model=args.model,
                        messages=[{"role": "user", "content": "Reply only: OK"}],
                        stream=False,
                        think=False,
                        keep_alive=-1,
                        options={"num_predict": 2, "num_ctx": 2048},
                    )
                    print("Ollama model ready.")
                except Exception as exc:
                    print(f"Model warm-up warning: {exc}")

            print(f"Brain provider: Ollama / {args.model}"
                  if not args.mock_brain else "Brain provider: MOCK")
            print(f"Live weather: ON (default {weather.default_location})")
            print("Internet search: " + ("ON" if web_search else "OFF"))
            if object_vision is None:
                print("Visual object recognition: OFF")
            else:
                vision_state = "READY" if object_vision.ready else "UNAVAILABLE"
                print(f"Visual object recognition: {vision_state}")
                if object_vision.error:
                    print(f"Visual model warning: {object_vision.error}")
            if google_lens is None:
                print("Google Lens-style web search: OFF")
            else:
                lens_state = "READY" if google_lens.ready else "FALLBACK ONLY"
                print(f"Google Lens-style web search: {lens_state}")
                if google_lens.error:
                    print(f"Google Lens setup: {google_lens.error}")
            print(f"Mode: {mode}")
            if listener is not None:
                print(
                    f"Voice input: ON ({args.audio_io} microphone; "
                    f"{args.whisper_model} on {args.whisper_device})"
                )
                if args.voice_mode == "conversation":
                    print("Hands-free conversation: ON")
                elif args.voice_mode == "wake":
                    print(
                        "Offline wake word: ON "
                        "(say 'Hey AURA', wait for 'Hmm?', then ask)"
                    )
                else:
                    print("Press Enter at the prompt to speak.")
            else:
                print("Voice input: OFF")
            print(
                "Spoken answers: "
                + ("ON" if speech is not None else "OFF")
            )
            print(
                "Face tracking: "
                + (f"ON (camera {args.camera_index})" if face_follower else "OFF")
            )
            if face_follower and args.face_recognition:
                people = face_follower.known_people()
                enrolled = ", ".join(people) if people else "none yet"
                state = "ON" if face_follower.recognition_ready else "UNAVAILABLE"
                print(f"Face recognition: {state} (enrolled: {enrolled})")
            print_help()

            def ask_text(
                text: str,
                source: str,
                request_id: str | None = None,
            ) -> None:
                bus.emit(
                    RobotEvent.QUESTION_RECEIVED,
                    {
                        "text": text,
                        "mode": mode,
                        "session": "desktop",
                        "request_id": request_id,
                    },
                    source=source,
                )

            def ask_and_wait(text: str, source: str) -> bool:
                """Ask one question, supporting a spoken stop at any time."""
                assistant_busy.set()
                request_id = f"{source}-{time.monotonic_ns()}"
                monitor_cancel = threading.Event()
                barge_in = threading.Event()
                monitor_thread: threading.Thread | None = None

                if speech is not None:
                    speech.allow_answers()

                def monitor_stop_commands() -> None:
                    if wake_listener is None:
                        return
                    try:
                        detection = wake_listener.wait_for_stop(monitor_cancel)
                    except Exception as exc:  # noqa: BLE001
                        if not monitor_cancel.is_set():
                            log.warning("barge-in monitor stopped: %s", exc)
                        return
                    if not detection.detected or monitor_cancel.is_set():
                        return

                    with cancelled_requests_lock:
                        cancelled_requests.add(request_id)
                    barge_in.set()
                    if speech is not None:
                        speech.suppress_request(request_id)
                        speech.cancel_all()
                    hardware.set_emotion("NORMAL")
                    print(
                        "\n[BARGE-IN] Stop command heard. "
                        "Returning to wake mode.\n"
                    )

                answer_ready.clear()
                speech_started.clear()
                speech_finished.clear()

                # Start the tiny local stop grammar before Qwen. The question
                # itself has already been captured, so this microphone stream
                # is dedicated only to barge-in detection.
                if wake_listener is not None and args.audio_io == "esp32":
                    monitor_thread = threading.Thread(
                        target=monitor_stop_commands,
                        name="aura-barge-in",
                        daemon=True,
                    )
                    monitor_thread.start()

                # EventBus delivery is normally synchronous. Run this one
                # request on its own thread so "AURA stop" can cancel while
                # Ollama is still generating.
                question_thread = threading.Thread(
                    target=ask_text,
                    args=(text, source, request_id),
                    name="aura-question",
                    daemon=True,
                )
                question_thread.start()

                try:
                    answer_deadline = time.monotonic() + 90.0
                    while not answer_ready.wait(timeout=0.05):
                        if barge_in.is_set():
                            return False
                        if time.monotonic() >= answer_deadline:
                            print(
                                "AURA took too long to answer. "
                                "Returning to wake mode."
                            )
                            with cancelled_requests_lock:
                                cancelled_requests.add(request_id)
                            if speech is not None:
                                speech.suppress_request(request_id)
                            return False

                    if barge_in.is_set():
                        return False

                    if speech is not None:
                        speech_deadline = time.monotonic() + 8.0
                        while not speech_started.wait(timeout=0.05):
                            if barge_in.is_set():
                                return False
                            if time.monotonic() >= speech_deadline:
                                break
                        if speech_started.is_set():
                            finish_deadline = time.monotonic() + 120.0
                            while not speech_finished.wait(timeout=0.05):
                                if barge_in.is_set():
                                    return False
                                if time.monotonic() >= finish_deadline:
                                    break
                    return not barge_in.is_set()
                finally:
                    monitor_cancel.set()
                    if monitor_thread is not None:
                        monitor_thread.join(timeout=3.0)
                    assistant_busy.clear()

            def say_and_wait(
                text: str,
                timeout_s: float = 20.0,
                emotion_during_speech: str | None = None,
            ) -> None:
                """Speak a short system prompt before reopening the microphone."""
                if speech is None:
                    return
                assistant_busy.set()
                try:
                    speech_started.clear()
                    speech_finished.clear()
                    speech.say(text, interrupt=True)
                    if speech_started.wait(timeout=5.0):
                        if emotion_during_speech:
                            hardware.set_emotion(emotion_during_speech)
                        speech_finished.wait(timeout=timeout_s)
                finally:
                    assistant_busy.clear()

            def show_next_alert(entry: ScheduledAlert, seconds: int) -> None:
                hardware.send_face_command(
                    timer_start_command(seconds, entry.kind),
                    priority=CommandPriority.HIGH,
                )

            def clear_alert_display() -> None:
                hardware.send_face_command(
                    timer_stop_command(),
                    priority=CommandPriority.HIGH,
                )
                hardware.set_emotion("NORMAL")

            def announce_expired_alert(entry: ScheduledAlert) -> None:
                hardware.send_face_command(
                    timer_alert_command(entry.kind),
                    priority=CommandPriority.CRITICAL,
                )
                alert_text = ReminderService.alert_text(entry)
                print(f"\n[ALERT] {alert_text}\n")
                try:
                    say_and_wait(alert_text, timeout_s=20.0)
                finally:
                    # The ReminderService clears the timer scene immediately
                    # after this callback returns.  Hold the alert for a few
                    # seconds first, even if audio playback was unavailable.
                    time.sleep(TIMER_ALERT_SCREEN_HOLD_S)

            reminders = ReminderService(
                on_display=show_next_alert,
                on_alert=announce_expired_alert,
                on_clear=clear_alert_display,
            )

            def start_focus_display(seconds: int) -> None:
                nonlocal mode, focus_previous_mode
                if mode != "FOCUS":
                    focus_previous_mode = mode
                mode = "FOCUS"
                hardware.send_face_command(
                    timer_start_command(seconds, "FOCUS"),
                    priority=CommandPriority.HIGH,
                )

            def pause_focus_display() -> None:
                hardware.send_face_command(
                    timer_stop_command(),
                    priority=CommandPriority.HIGH,
                )
                hardware.set_emotion("SLEEPY")

            def resume_focus_display(seconds: int) -> None:
                nonlocal mode
                mode = "FOCUS"
                hardware.send_face_command(
                    timer_start_command(seconds, "FOCUS"),
                    priority=CommandPriority.HIGH,
                )

            def leave_focus_display() -> None:
                nonlocal mode
                hardware.send_face_command(
                    timer_stop_command(),
                    priority=CommandPriority.HIGH,
                )
                hardware.set_emotion("NORMAL")
                mode = focus_previous_mode

            def announce_focus_complete() -> None:
                nonlocal mode
                hardware.send_face_command(
                    timer_alert_command("FOCUS"),
                    priority=CommandPriority.CRITICAL,
                )
                message = "Focus session complete. Great work, Kavy."
                print(f"\n[FOCUS] {message}\n")
                try:
                    say_and_wait(message, timeout_s=20.0)
                finally:
                    time.sleep(TIMER_ALERT_SCREEN_HOLD_S)
                    leave_focus_display()

            focus = FocusStudyService(
                on_start=start_focus_display,
                on_pause=pause_focus_display,
                on_resume=resume_focus_display,
                on_stop=leave_focus_display,
                on_complete=announce_focus_complete,
            )

            focus_warning_lock = threading.Lock()

            def warn_about_focus_distraction(kind: str) -> None:
                """Briefly warn, then return to the live focus countdown."""
                if focus is None or not focus.active or focus.paused:
                    return
                if not focus_warning_lock.acquire(blocking=False):
                    return
                try:
                    # Re-check after taking the lock so a session that ended
                    # in the meantime is never revived on the display.
                    if focus is None or not focus.active or focus.paused:
                        return
                    remaining = focus.remaining_seconds()
                    hardware.send_face_command(
                        timer_stop_command(),
                        priority=CommandPriority.HIGH,
                    )
                    hardware.set_emotion("WORRIED")
                    if kind == "phone":
                        message = "Kavy, please put the phone down and stay focused."
                        label = "Phone distraction"
                    else:
                        message = "Kavy, come back to your focus session."
                        label = "Prolonged absence"
                    print(f"\n[FOCUS] {label} detected.\n")
                    if speech is not None:
                        say_and_wait(
                            message,
                            timeout_s=12.0,
                            emotion_during_speech="WORRIED",
                        )
                    else:
                        time.sleep(1.5)
                finally:
                    if focus is not None and focus.active and not focus.paused:
                        hardware.send_face_command(
                            timer_start_command(
                                max(1, focus.remaining_seconds()),
                                "FOCUS",
                            ),
                            priority=CommandPriority.HIGH,
                        )
                    focus_warning_lock.release()

            if (
                args.focus_distraction
                and focus is not None
                and face_follower is not None
                and object_vision is not None
            ):
                focus_monitor = FocusDistractionMonitor(
                    focus_active=lambda: bool(focus and focus.active),
                    focus_paused=lambda: bool(focus and focus.paused),
                    snapshot=face_follower.snapshot,
                    detect=object_vision.detect,
                    person_visible=lambda: face_follower.face_visible,
                    busy=lambda: (
                        assistant_busy.is_set()
                        or voice_capture_active.is_set()
                        or hardware.audio_link.speaker_active
                    ),
                    on_warning=warn_about_focus_distraction,
                    config=FocusDistractionConfig(
                        phone_persist_s=max(1.0, args.focus_phone_seconds),
                        absence_persist_s=max(5.0, args.focus_absence_seconds),
                        warning_cooldown_s=max(10.0, args.focus_warning_cooldown),
                    ),
                )
                focus_monitor.start()
                print(
                    "Focus distraction detection: ON "
                    f"(phone {max(1.0, args.focus_phone_seconds):g}s, "
                    f"absence {max(5.0, args.focus_absence_seconds):g}s)"
                )
            elif args.focus_distraction:
                print(
                    "Focus distraction detection: UNAVAILABLE "
                    "(camera and local object recognition are required)"
                )
            else:
                print("Focus distraction detection: OFF")

            def handle_focus_command(text: str) -> bool:
                """Handle timed study sessions locally without asking Qwen."""
                if focus is None:
                    return False
                reply = focus.handle(text)
                if not reply.handled:
                    return False
                print(f"\nAURA: {reply.text}\n")
                if speech is not None:
                    say_and_wait(reply.text, timeout_s=12.0)
                return True

            def handle_time_command(text: str) -> bool:
                """Handle timers/reminders locally instead of asking Qwen."""
                if reminders is None:
                    return False
                reply = reminders.handle(text)
                if not reply.handled:
                    return False
                print(f"\nAURA: {reply.text}\n")
                if speech is not None:
                    say_and_wait(reply.text, timeout_s=12.0)
                return True

            def handle_music_command(text: str) -> bool:
                """Run a music request locally instead of sending it to Qwen."""
                if not music.handles(text):
                    return False
                return music.handle(text, lambda reply: say_and_wait(reply, 12.0))

            def handle_visual_question(text: str) -> bool:
                """Answer a camera question through web matching with local fallback."""
                if not ObjectVisionService.handles(text):
                    return False

                hardware.set_emotion("THINKING")
                if object_vision is None and google_lens is None:
                    result_text = "Visual object recognition is turned off."
                    success = False
                elif face_follower is None or not face_follower.health_check():
                    result_text = "I cannot access the camera right now."
                    success = False
                else:
                    frame = face_follower.snapshot()
                    lens_frame = frame
                    if object_vision is not None and frame is not None:
                        lens_frame, focus_observations, focus_label = (
                            object_vision.focus_frame(text, frame)
                        )
                        if focus_label:
                            focused = next(
                                (
                                    item
                                    for item in focus_observations
                                    if item.label == focus_label
                                ),
                                None,
                            )
                            suffix = (
                                f" {focused.confidence:.0%}"
                                if focused is not None
                                else ""
                            )
                            print(f"[LENS] Focused crop: {focus_label}{suffix}")
                    lens_result = (
                        google_lens.identify(text, lens_frame)
                        if google_lens is not None and google_lens.ready
                        else None
                    )
                    if lens_result is not None and lens_result.success:
                        result_text = lens_result.text
                        success = True
                        if lens_result.candidates:
                            print(
                                "[LENS] Matches: "
                                + ", ".join(lens_result.candidates[:5])
                            )
                        for source in lens_result.sources:
                            print(
                                f"[LENS] Source: {source.title or source.url}"
                                + (f" — {source.url}" if source.title else "")
                            )
                    else:
                        # Credentials, network, or matching can fail without
                        # affecting AURA. The prior local detector remains the
                        # automatic and privacy-friendly fallback.
                        if object_vision is None:
                            result_text = (
                                lens_result.text
                                if lens_result is not None
                                else "Google image search is unavailable."
                            )
                            success = False
                        else:
                            result = object_vision.describe(text, frame)
                            result_text = result.text
                            success = result.success
                            if result.observations:
                                details = ", ".join(
                                    f"{item.label} {item.confidence:.0%}"
                                    for item in result.observations
                                )
                                print(f"[VISION] Detected: {details}")
                            if result.error:
                                log.warning("visual question: %s", result.error)
                        if lens_result is not None and lens_result.error:
                            log.info("Lens fallback: %s", lens_result.error)

                print(f"\nAURA: {result_text}\n")
                hardware.set_emotion("HAPPY" if success else "CONFUSED")
                if speech is not None:
                    say_and_wait(result_text, timeout_s=12.0)
                return True

            def play_wake_acknowledgement() -> None:
                """Complete the spoken acknowledgement before recording."""
                try:
                    acknowledge_wake(
                        microphone,
                        lambda text: say_and_wait(
                            text, timeout_s=5.0, emotion_during_speech="HAPPY",
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("wake acknowledgement cue failed: %s", exc)

            def capture_voice(*, force_calibration: bool = False,
                              wait_for_speech_s: float | None = None,
                              speak_on_failure: bool = True,
                              report_no_speech: bool = True,
                              reject_speaker_tail: bool = False,
                              listening_emotion: str = "CURIOUS",
                              initial_audio: bytes = b""):
                if listener is None:
                    print("Voice input is disabled. Restart without --no-voice.")
                    return None
                if speech is not None:
                    speech.cancel_all()
                hardware.send_face_command(
                    "MOTOR:TOP:QUIET:ON", priority=CommandPriority.HIGH,
                )
                hardware.set_emotion(listening_emotion)
                voice_capture_active.set()
                try:
                    result = listener.listen(
                        wait_for_speech_s=wait_for_speech_s,
                        force_calibration=force_calibration,
                        initial_audio=initial_audio,
                    )
                finally:
                    voice_capture_active.clear()
                    hardware.send_face_command(
                        "MOTOR:TOP:QUIET:OFF", priority=CommandPriority.HIGH,
                    )
                if not result.success:
                    is_uncertain = bool(result.text)
                    hardware.set_emotion("CONFUSED" if is_uncertain else "NORMAL")
                    if is_uncertain and report_no_speech:
                        print(
                            f"[VOICE] Uncertain transcript: {result.text} "
                            f"(confidence {result.confidence:.0%})"
                        )
                    if report_no_speech:
                        print(f"[VOICE] {result.error}")
                    if is_uncertain and speak_on_failure:
                        say_and_wait(
                            "Sorry, I did not understand that clearly. "
                            "Please say it again.",
                        )
                        hardware.set_emotion("NORMAL")
                    return None
                if reject_speaker_tail:
                    normalized = re.sub(
                        r"[^a-z]+",
                        " ",
                        result.text.lower(),
                    ).strip()
                    known_tail_hallucinations = {
                        "thank you",
                        "thanks",
                        "you",
                        "bye",
                        "goodbye",
                    }
                    # This stricter check applies only in the five-second
                    # follow-up window immediately after AURA speaks, where
                    # weak recognition is usually residual speaker audio.
                    if result.confidence < 0.50:
                        print(
                            "[FOLLOW-UP] Ignored low-confidence residual audio."
                        )
                        return None
                    if (
                        result.confidence < 0.65
                        and normalized in known_tail_hallucinations
                    ):
                        print(
                            "[FOLLOW-UP] Ignored a low-confidence "
                            "speaker-tail echo."
                        )
                        return None
                print(
                    f"\nYou said: {result.text}"
                    f"  [confidence {result.confidence:.0%}; "
                    f"STT {result.transcription_time_s:.2f}s]\n"
                )
                return result.text

            def listen_once() -> None:
                text = capture_voice()
                if text:
                    # Do not return to the typing prompt while AURA is still
                    # generating or playing its spoken response.
                    ask_and_wait(text, "microphone")

            def handle_spoken_face_command(text: str) -> bool:
                """Handle face enrollment without sending it to Qwen."""
                normalized = re.sub(r"[^a-z]+", " ", text.casefold()).strip()
                enrollment_phrases = {
                    "learn my face",
                    "remember my face",
                    "recognize my face",
                    "recognise my face",
                    "enroll my face",
                    "enrol my face",
                }
                if normalized not in enrollment_phrases:
                    return False
                if face_follower is None or not face_follower.recognition_ready:
                    say_and_wait("Sorry, face recognition is unavailable.")
                    return True
                say_and_wait(
                    f"Okay {args.face_owner_name}. Look at the camera and turn "
                    "your face slightly left and right."
                )
                face_follower.enroll(args.face_owner_name)
                return True

            def hands_free_loop(require_wake_word: bool) -> None:
                if listener is None:
                    print("Voice input is disabled. Restart without --no-voice.")
                    return
                mode_name = "WAKE-WORD" if require_wake_word else "CONVERSATION"
                print(f"\n{mode_name} MODE ON")
                if require_wake_word:
                    print(
                        "Say 'Hey AURA', wait for 'Hmm?', "
                        "then ask your question or command."
                    )
                else:
                    print("AURA will listen again after each spoken answer.")
                print(
                    "Say 'AURA stop', 'AURA shut up', or "
                    "'AURA keep quiet' at any time to return to wake mode.\n"
                )

                first_turn = True
                if require_wake_word:
                    if wake_listener is None:
                        print("The offline wake-word listener is unavailable.")
                        return
                    if not listener.calibrate():
                        print("Microphone calibration failed; wake mode stopped.")
                        return
                    first_turn = False
                while True:
                    music_interrupted = False
                    if require_wake_word:
                        hardware.set_emotion("NORMAL")
                        try:
                            detection = wake_listener.wait()
                        except MicrophoneError as exc:
                            # A missing USB audio packet must not terminate the
                            # whole assistant.  Reset the ESP32 mic session and
                            # let the next loop reopen it automatically.
                            log.warning(
                                "wake microphone stream interrupted; "
                                "recovering: %s",
                                exc,
                            )
                            print(
                                "[WAKE] Microphone stream interrupted. "
                                "Reconnecting automatically..."
                            )
                            try:
                                microphone.close()
                            except Exception as close_exc:  # noqa: BLE001
                                log.debug(
                                    "microphone recovery close failed: %s",
                                    close_exc,
                                )
                            time.sleep(0.25)
                            continue
                        if not detection.detected:
                            continue
                        print(
                            f"\n[WAKE] Hey AURA detected "
                            f"in {detection.elapsed_s:.2f}s."
                        )
                        music_interrupted = music.interrupt_for_assistant()
                        hardware.set_emotion("HAPPY")
                        # Two-step conversation: wake audio is activation only.
                        # Finish the audible cue before opening a fresh stream.
                        play_wake_acknowledgement()
                        print(
                            "[WAKE] Listening now—ask your question or command."
                        )

                    text = capture_voice(
                        force_calibration=first_turn,
                        wait_for_speech_s=8.0 if require_wake_word else None,
                        speak_on_failure=not require_wake_word,
                        listening_emotion=(
                            "HAPPY" if require_wake_word else "CURIOUS"
                        ),
                        initial_audio=b"",
                    )
                    first_turn = False
                    if not text:
                        if require_wake_word:
                            # Stay awake for one natural retry.  The user does
                            # not need to repeat the wake phrase after a clipped
                            # or uncertain first attempt.
                            print(
                                "[WAKE] I did not catch the full question. "
                                "Please repeat only your question now."
                            )
                            hardware.set_emotion("HAPPY")
                            text = capture_voice(
                                wait_for_speech_s=8.0,
                                speak_on_failure=False,
                                listening_emotion="HAPPY",
                            )
                        if not text:
                            if music_interrupted:
                                music.resume_after_assistant()
                            continue
                    if require_wake_word:
                        cleaned = re.sub(
                            r"^\s*(?:(?:hey|hi|okay|ok)\s+)?"
                            r"(?:aura|ora|or\s+a)\b[\s,.:;!?-]*",
                            "",
                            text,
                            flags=re.IGNORECASE,
                        ).strip()
                        text = cleaned
                        if not text:
                            # The user said only the wake phrase. Keep the
                            # already-open conversational turn and wait for
                            # the actual question without another wake word.
                            print(
                                "[WAKE] Ready. Ask your question now."
                            )
                            text = capture_voice(
                                wait_for_speech_s=8.0,
                                speak_on_failure=False,
                                listening_emotion="HAPPY",
                            )
                            if not text:
                                continue
                    question = text

                    # Stay in one conversational session. After every spoken
                    # answer, listen for a follow-up for exactly five seconds.
                    # The five seconds apply only to when speech must START;
                    # once it starts, the normal endpointer captures the whole
                    # sentence.
                    while question:
                        if is_stop_phrase(question):
                            hardware.set_emotion("NORMAL")
                            print("[WAKE] Returning to wake mode.\n")
                            break

                        if handle_spoken_face_command(question):
                            print("[WAKE] Face enrollment started. Returning to wake mode.\n")
                            break

                        if handle_focus_command(question):
                            completed = True
                        elif handle_time_command(question):
                            completed = True
                        elif handle_music_command(question):
                            # The music command now owns the playback state.
                            music_interrupted = False
                            break
                        elif handle_visual_question(question):
                            completed = True
                        else:
                            completed = ask_and_wait(question, "microphone")
                        if not completed:
                            break

                        print(
                            "[FOLLOW-UP] Listening for 5 seconds. "
                            "You can continue without saying Hey AURA."
                        )
                        # Let the final amplifier/DMA tail settle before
                        # opening the follow-up recognizer.
                        time.sleep(0.30)
                        question = capture_voice(
                            wait_for_speech_s=5.0,
                            speak_on_failure=False,
                            report_no_speech=False,
                            reject_speaker_tail=True,
                            listening_emotion="HAPPY",
                        )
                        if not question:
                            hardware.set_emotion("NORMAL")
                            print("[FOLLOW-UP] No follow-up. Returning to wake mode.\n")
                            break

                    if music_interrupted:
                        music.resume_after_assistant()

            # Confirm the complete TTS -> USB -> ES8311 -> speaker path before
            # entering an indefinite wake-word listening session. Previously
            # startup was silent, which made a missed wake phrase look like a
            # broken speaker even though no answer had been queued.
            if speech is not None and args.audio_io == "esp32":
                print("[AUDIO] Verifying robot speaker...")
                say_and_wait(
                    "AURA is ready.",
                    timeout_s=12.0,
                )

            if args.voice_mode == "conversation":
                hands_free_loop(False)
            elif args.voice_mode == "wake":
                hands_free_loop(True)

            while True:
                try:
                    prompt = (
                        "You (type, or Enter to speak): "
                        if listener is not None
                        else "You: "
                    )
                    user_text = input(prompt).strip()
                except EOFError:
                    break

                if not user_text:
                    if listener is not None:
                        listen_once()
                    continue

                lower = user_text.lower()
                if lower in {"/quit", "/exit", "quit", "exit"}:
                    break

                if lower == "/help":
                    print_help()
                    continue

                if lower == "/listen":
                    listen_once()
                    continue

                if lower == "/mics":
                    if args.audio_io == "esp32":
                        print("  ESP32 onboard MEMS microphone via ES8311 (selected)")
                        print("  Restart with --audio-io laptop to list laptop mics.")
                        continue
                    for device in PushToTalkListener.input_devices():
                        if "error" in device:
                            print(f"Microphone query failed: {device['error']}")
                        else:
                            marker = " *" if device["index"] == args.mic else ""
                            print(
                                f"  {device['index']}: {device['name']} "
                                f"({device['channels']} input channel(s)){marker}"
                            )
                    continue

                if lower == "/audio":
                    if args.audio_io != "esp32":
                        print("Audio I/O is set to laptop.")
                    elif hardware.audio_link.probe(timeout_s=2.0):
                        print("ESP32 ES8311 audio link is ready.")
                    else:
                        print("ESP32 audio check failed: "
                              f"{hardware.audio_link.last_error or 'no reply'}")
                    continue

                if lower == "/speaker-test":
                    if speech is None:
                        print("Spoken answers are disabled.")
                    else:
                        print("[AUDIO] Playing the robot-speaker test...")
                        speech.say(
                            "Hello Kavya. This is AURA speaking through the robot speaker.",
                            emotion_hint="HAPPY",
                            priority=10,
                            interrupt=True,
                        )
                    continue

                if lower == "/music":
                    print("[MUSIC] " + music.status_text())
                    continue

                if lower.startswith("/play "):
                    handle_music_command("play " + user_text.split(maxsplit=1)[1])
                    continue

                if lower == "/pause":
                    handle_music_command("pause music")
                    continue

                if lower == "/resume":
                    handle_music_command("resume music")
                    continue

                if lower == "/next":
                    handle_music_command("next song")
                    continue

                if lower == "/previous":
                    handle_music_command("previous song")
                    continue

                if lower == "/music stop":
                    handle_music_command("stop music")
                    continue

                if lower == "/vision":
                    if face_follower is None:
                        print("Face tracking is disabled.")
                    else:
                        state = "READY" if face_follower.health_check() else "UNAVAILABLE"
                        print(f"Face tracking: {state} (camera {args.camera_index})")
                    continue

                if lower == "/see":
                    handle_visual_question("What can you see?")
                    continue

                if lower == "/lens":
                    handle_visual_question("Identify this object")
                    continue

                if lower.startswith("/enroll "):
                    name = user_text.split(maxsplit=1)[1].strip()
                    if face_follower is None or not face_follower.recognition_ready:
                        print("Face recognition is unavailable.")
                    elif face_follower.enroll(name):
                        print(
                            f"[RECOGNITION] Look at the camera while AURA learns {name}. "
                            "Turn your face slightly left and right."
                        )
                    continue

                if lower == "/faces":
                    if face_follower is None or not face_follower.recognition_ready:
                        print("Face recognition is unavailable.")
                    else:
                        people = face_follower.known_people()
                        print(
                            "Enrolled people: " + (", ".join(people) if people else "none")
                        )
                    continue

                if lower.startswith("/forget "):
                    name = user_text.split(maxsplit=1)[1].strip()
                    if face_follower is None or not face_follower.recognition_ready:
                        print("Face recognition is unavailable.")
                    elif not face_follower.forget_person(name):
                        print(f"No enrolled face named {name}.")
                    continue

                if lower.startswith("/volume "):
                    try:
                        percent = int(user_text.split(maxsplit=1)[1])
                    except ValueError:
                        print("Use /volume followed by 0 to 100.")
                    else:
                        percent = max(0, min(100, percent))
                        if args.audio_io == "esp32":
                            hardware.audio_link.set_volume(percent)
                        if speech is not None:
                            speech.set_volume(percent / 100.0)
                        print(f"Speaker volume set to {percent}%")
                    continue

                if lower == "/calibrate":
                    if listener is None:
                        print("Voice input is disabled.")
                    else:
                        listener.request_recalibration()
                        print("The microphone will recalibrate on your next listen.")
                    continue

                if lower in {"/conversation", "/conversation on"}:
                    hands_free_loop(False)
                    continue

                if lower in {"/wake", "/wake on"}:
                    hands_free_loop(True)
                    continue

                if lower.startswith("/say "):
                    if speech is None:
                        print("Spoken answers are disabled.")
                    else:
                        speech.say(
                            user_text.split(maxsplit=1)[1],
                            interrupt=True,
                        )
                    continue

                if lower == "/stop":
                    if speech is not None:
                        speech.cancel_all()
                    continue

                if lower.startswith("/emotion "):
                    token = user_text.split(maxsplit=1)[1]
                    hardware.set_emotion(token)
                    continue

                if lower == "/blink":
                    hardware.send_face_command("BLINK")
                    continue

                if lower in {"/focus on", "/focus start"}:
                    handle_focus_command("start focus mode")
                    continue

                if lower == "/focus off":
                    handle_focus_command("stop focus mode")
                    continue

                if lower == "/focus pause":
                    handle_focus_command("pause focus mode")
                    continue

                if lower == "/focus resume":
                    handle_focus_command("resume focus mode")
                    continue

                if lower == "/focus status":
                    handle_focus_command("focus status")
                    continue

                if re.fullmatch(r"/focus\s+\d+", lower):
                    minutes = int(lower.split()[1])
                    if not 1 <= minutes <= 480:
                        print("Focus duration must be between 1 and 480 minutes.")
                    else:
                        handle_focus_command(
                            f"start focus mode for {minutes} minutes"
                        )
                    continue

                if lower == "/status":
                    hardware.send_face_command("STATUS")
                    continue

                if lower == "/timers":
                    if reminders is not None:
                        print(reminders.status_text())
                    continue

                if lower in {"/cancel timers", "/cancel reminders", "/cancel alarms"}:
                    if reminders is not None:
                        kind = lower.removeprefix("/cancel ").rstrip("s")
                        count = reminders.cancel(kind)
                        print(
                            f"Cancelled {count} {kind}{'' if count == 1 else 's'}."
                            if count
                            else f"There is no active {kind}."
                        )
                    continue

                if lower.startswith("/mode "):
                    mode = user_text.split(maxsplit=1)[1].strip().upper()
                    print(f"Mode changed to {mode}")
                    continue

                if handle_focus_command(user_text):
                    continue

                if handle_time_command(user_text):
                    continue

                if handle_music_command(user_text):
                    continue

                if handle_visual_question(user_text):
                    continue

                # Typed questions use the same event path as microphone input.
                ask_text(user_text, "console")

            hardware.send_face_command(
                "SHUTDOWN",
                priority=CommandPriority.CRITICAL,
            )
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nStopping AURA...")
    except Exception as exc:  # keep CLI error understandable
        log.exception("AURA runtime failed")
        print(f"\nAURA failed: {exc}")
        return 1
    finally:
        if focus_monitor is not None:
            focus_monitor.stop()
        if focus is not None:
            focus.close()
        if reminders is not None:
            reminders.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
