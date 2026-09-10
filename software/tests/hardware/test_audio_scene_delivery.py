"""Timer and emotion updates must arrive while wake capture stays open."""
import time

from core.event_bus import EventBus
from hardware.hardware_manager import HardwareManager
from hardware.hardware_config import HardwareConfig
from hardware.serial_manager import MockSerialTransport
from hardware.serial_manager import SerialManager
from hardware.hardware_config import SerialConfig
from hardware.device_types import CommandPriority


def test_wake_capture_delivers_timer_and_emotion_without_gaze_traffic():
    def reply(line):
        return {
            "MIC START": ["MIC BEGIN 16000 320"],
            "MIC STOP": ["MIC END"],
        }.get(line, ["OK"])
    transport = MockSerialTransport(responder=reply)
    config = HardwareConfig()
    config.health.enabled = False
    hardware = HardwareManager(EventBus(), config, transport)
    hardware.initialize()
    hardware.start()
    try:
        hardware.audio_link.start_microphone()
        hardware.send_face_command("GAZE 0.5 0.0", priority=CommandPriority.LOW)
        hardware.send_face_command("TIMER STOP", priority=CommandPriority.HIGH)
        hardware.set_emotion("THINKING")
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and "THINK" not in transport.written:
            time.sleep(0.005)
        assert "TIMER STOP" in transport.written
        assert "THINK" in transport.written
        assert "GAZE 0.5 0.0" not in transport.written
        hardware.audio_link.stop_microphone()
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and "GAZE 0.5 0.0" not in transport.written:
            time.sleep(0.005)
        assert "GAZE 0.5 0.0" in transport.written
    finally:
        hardware.audio_link.stop_microphone()
        hardware.stop()


def test_long_wake_wait_keeps_only_latest_camera_targets():
    serial = SerialManager(EventBus(), SerialConfig(), MockSerialTransport())
    serial.pause_queued_writes()
    for i in range(1000):
        assert serial.send(f"GAZE {i / 1000:.3f} 0", CommandPriority.LOW)
        assert serial.send(f"SERVO:HEAD:{80 + i % 30}", CommandPriority.LOW)
    assert len(serial._heap) == 2
    assert {item.line for item in serial._heap} == {"GAZE 0.999 0", "SERVO:HEAD:89"}
    assert serial.send("TIMER STOP", CommandPriority.HIGH)


def test_head_target_waits_for_handshake_but_not_wake_stream():
    serial = SerialManager(EventBus(), SerialConfig(), MockSerialTransport())
    serial.pause_queued_writes()
    serial.send("GAZE 0.5 0", CommandPriority.LOW)
    serial.send("SERVO:HEAD:104", CommandPriority.LOW)
    head = next(item for item in serial._heap if item.line.startswith("SERVO:"))
    gaze = next(item for item in serial._heap if item.line.startswith("GAZE"))
    assert serial._command_blocked(head)
    serial.resume_priority_commands()
    assert not serial._command_blocked(head)
    assert serial._command_blocked(gaze)
    assert serial._heap[0] is head  # blocked gaze cannot hold up the head
    serial.pause_queued_writes()  # stopping/restarting audio is exclusive too
    assert serial._command_blocked(head)


def test_head_tracking_delivered_with_microphone_open():
    def reply(line):
        return {"MIC START": ["MIC BEGIN 16000 320"],
                "MIC STOP": ["MIC END"]}.get(line, ["OK"])

    transport = MockSerialTransport(responder=reply)
    config = HardwareConfig()
    config.health.enabled = False
    hardware = HardwareManager(EventBus(), config, transport)
    hardware.initialize()
    hardware.start()
    try:
        hardware.audio_link.start_microphone()
        hardware.send_face_command("GAZE 0.5 0", priority=CommandPriority.LOW)
        for angle in (86, 104, 95):
            command = f"SERVO:HEAD:{angle}"
            hardware.send_face_command(command, priority=CommandPriority.LOW)
            deadline = time.monotonic() + 0.5
            while command not in transport.written and time.monotonic() < deadline:
                time.sleep(0.005)
            assert command in transport.written
        assert "MIC STOP" not in transport.written
        assert "GAZE 0.5 0" not in transport.written
    finally:
        hardware.audio_link.stop_microphone()
        hardware.stop()


def test_music_visualizer_updates_are_current_and_allowed_during_audio():
    from music.controller import MusicController

    class Hardware:
        def send_face_command(self, line, *, priority):
            assert serial.send(line, priority)

    serial = SerialManager(EventBus(), SerialConfig(), MockSerialTransport())
    serial.pause_queued_writes()
    controller = MusicController(Hardware())
    for level in range(100):
        controller._send(f"MUSIC LEVEL {level}", low_priority=True)
    assert len(serial._heap) == 1
    assert serial._heap[0].line == "MUSIC LEVEL 99"
    assert serial._command_blocked(serial._heap[0])
    serial.resume_priority_commands()
    assert not serial._command_blocked(serial._heap[0])
