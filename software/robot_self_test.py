"""AURA end-to-end ESP32 hardware self-test.

Run only while the normal AURA program and Arduino Serial Monitor are closed.
The test is intentionally conservative: it restores the display, motor, servo,
volume, and audio mode before closing the port, even after a failure.
"""
from __future__ import annotations

import argparse
import array
import base64
import json
import math
import pathlib
import statistics
import sys
import time
from dataclasses import dataclass

import serial
from hardware.serial_manager import PySerialTransport


ROOT = pathlib.Path(__file__).resolve().parent
SETTINGS = ROOT / "aura_settings.json"


@dataclass
class Result:
    name: str
    state: str
    detail: str = ""


class AuraSerialTest:
    def __init__(self, port: str, baud: int = 921_600) -> None:
        self.port = port
        self.baud = baud
        self.serial: serial.Serial | None = None
        self.transport = PySerialTransport()
        self.results: list[Result] = []

    def report(self, name: str, passed: bool, detail: str = "") -> bool:
        state = "PASS" if passed else "FAIL"
        self.results.append(Result(name, state, detail))
        suffix = f" - {detail}" if detail else ""
        print(f"[{state}] {name}{suffix}")
        return passed

    def skip(self, name: str, detail: str) -> None:
        self.results.append(Result(name, "MANUAL", detail))
        print(f"[MANUAL] {name} - {detail}")

    def open(self) -> None:
        self.transport.open(self.port, self.baud, 0.08, 2.0)
        self.serial = self.transport._serial
        # Opening the S3 USB serial connection can reset the firmware. Give it
        # time to initialise the display, codec, motor, servo, and touch bus.
        self.serial.reset_input_buffer()
        time.sleep(2.8)

    def close(self) -> None:
        if self.serial is not None:
            self.transport.close()
            self.serial = None

    def send(self, command: str) -> None:
        assert self.serial is not None
        self.serial.write((command + "\n").encode("utf-8"))
        self.serial.flush()

    def read_until(self, predicate, timeout: float = 2.0) -> str | None:
        assert self.serial is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.transport.read_line()
            if line is None:
                continue
            if line.startswith("MIC:"):
                continue
            if predicate(line):
                return line
        return None

    def command(self, command: str, expected, timeout: float = 2.0) -> str | None:
        self.send(command)
        return self.read_until(expected, timeout)

    def test_serial_and_face(self) -> None:
        pong = self.command("PING", lambda line: line == "PONG", 3.0)
        self.report("ESP32 serial handshake", pong == "PONG", pong or "no PONG")

        status = self.command("STATUS", lambda line: line.startswith("STATUS "))
        self.report("Firmware status", status is not None, status or "no status reply")

        bad = self.command("AURA_SELF_TEST_UNKNOWN", lambda line: line.startswith("ERR"))
        self.report("Unknown-command safety", bad is not None, bad or "no error reply")

        emotions = [
            "NEUTRAL", "HAPPY", "EXCITED", "SAD", "ANGRY", "SURPRISED",
            "CONFUSED", "CURIOUS", "LOVE", "THINK", "LISTEN", "SEARCH",
            "WORRIED", "CELEBRATE", "SLEEPY",
        ]
        failed: list[str] = []
        for emotion in emotions:
            reply = self.command(emotion, lambda line: line == "OK", 1.5)
            if reply != "OK":
                failed.append(emotion)
            time.sleep(0.12)
        self.report(
            "All face-emotion commands",
            not failed,
            f"{len(emotions) - len(failed)}/{len(emotions)} accepted"
            + (f"; failed: {', '.join(failed)}" if failed else ""),
        )

        animation_commands = [
            "BLINK", "DOUBLE_BLINK", "LOOK LEFT", "LOOK RIGHT", "LOOK UP",
            "LOOK DOWN", "LOOK CENTER", "GAZE -0.65 0.30", "GAZE 0.65 -0.30",
            "GAZE 0 0", "SLEEP", "WAKE",
        ]
        failed = []
        for item in animation_commands:
            reply = self.command(item, lambda line: line == "OK", 1.5)
            if reply != "OK":
                failed.append(item)
            time.sleep(0.10)
        self.report(
            "Blink, gaze, sleep and wake",
            not failed,
            f"{len(animation_commands) - len(failed)}/{len(animation_commands)} accepted"
            + (f"; failed: {', '.join(failed)}" if failed else ""),
        )

        scenes = ["BOOK START", "BOOK STOP", "TIMER START 4 TEST", "TIMER ALERT TEST", "TIMER STOP"]
        failed = []
        for item in scenes:
            reply = self.command(item, lambda line: line == "OK", 1.8)
            if reply != "OK":
                failed.append(item)
            time.sleep(0.35)
        self.report(
            "Focus book, countdown and alert scenes",
            not failed,
            f"{len(scenes) - len(failed)}/{len(scenes)} accepted"
            + (f"; failed: {', '.join(failed)}" if failed else ""),
        )

        bright = self.command("BRIGHTNESS 180", lambda line: line == "OK")
        self.command("BRIGHTNESS 255", lambda line: line == "OK")
        self.report("Display brightness control", bright == "OK", "restored to 255")

        # Music rendering commands deliberately have no ACK in the firmware.
        # A final STATUS proves the command parser remains responsive afterwards.
        for item in ("MUSIC START", "MUSIC LEVEL 35", "MUSIC PAUSE 1", "MUSIC PAUSE 0", "MUSIC HIDE", "MUSIC SHOW", "MUSIC STOP"):
            self.send(item)
            time.sleep(0.08)
        status = self.command("STATUS", lambda line: line.startswith("STATUS "), 2.5)
        self.report("Music visualizer protocol", status is not None, "command stream accepted")

    def test_motion(self) -> None:
        failed: list[str] = []
        for angle in (95, 86, 104, 95):
            reply = self.command(f"SERVO:HEAD:{angle}", lambda line: line == "OK", 1.5)
            if reply != "OK":
                failed.append(str(angle))
            time.sleep(0.45)
        self.report(
            "Head servo movement",
            not failed,
            "small left/right sweep; restored to centre" if not failed else f"failed angles: {failed}",
        )

        before = self.command("MOTOR:TOP:STATUS", lambda line: line.startswith("MOTOR TOP "), 2.0)
        started = self.command("MOTOR:TOP:TEST", lambda line: "MOTOR_TEST_STARTED" in line, 2.0)
        completed = self.read_until(lambda line: line == "MOTOR TEST COMPLETE STOPPED", 7.0)
        stopped = self.command("MOTOR:TOP:STOP", lambda line: "MOTOR_STOPPED" in line, 2.0)
        passed = all((before, started, completed, stopped))
        self.report(
            "Top motor/propeller",
            passed,
            "built-in forward/reverse test completed and stopped" if passed else
            f"status={before!r}, start={started!r}, complete={completed!r}, stop={stopped!r}",
        )

    def test_microphone(self) -> None:
        info = self.command("AUDIO INFO", lambda line: line.startswith("AUDIO "), 3.0)
        self.report("ES8311 audio codec", bool(info and info.startswith("AUDIO READY")), info or "no reply")

        self.send("MIC START")
        begin = self.read_until(lambda line: line.startswith("MIC BEGIN") or line.startswith("AUDIO ERROR"), 3.0)
        if not begin or not begin.startswith("MIC BEGIN"):
            self.report("ESP32 microphone stream", False, begin or "microphone did not start")
            self.send("MIC STOP")
            return

        assert self.serial is not None
        frames: list[bytes] = []
        malformed = 0
        deadline = time.monotonic() + 1.25
        while time.monotonic() < deadline and len(frames) < 55:
            line = self.transport.read_line()
            if line is None:
                continue
            if not line.startswith("MIC:"):
                continue
            try:
                pcm = base64.b64decode(line[4:], validate=True)
            except Exception:
                malformed += 1
                continue
            if len(pcm) == 640:
                frames.append(pcm)
            else:
                malformed += 1

        self.send("MIC STOP")
        ended = self.read_until(lambda line: line == "MIC END", 2.0)
        samples = array.array("h")
        for frame in frames:
            samples.frombytes(frame)
        if sys.byteorder != "little":
            samples.byteswap()
        normal = [sample / 32768.0 for sample in samples]
        rms = math.sqrt(statistics.fmean(value * value for value in normal)) if normal else 0.0
        peak = max((abs(value) for value in normal), default=0.0)
        clipping = (sum(abs(value) >= 0.98 for value in normal) / len(normal)) if normal else 1.0
        passed = len(frames) >= 30 and malformed == 0 and ended == "MIC END" and 0.00001 < rms < 0.60 and clipping < 0.05
        self.report(
            "ESP32 microphone stream",
            passed,
            f"{len(frames)} frames, RMS={rms:.4f}, peak={peak:.3f}, malformed={malformed}, clipping={clipping:.1%}",
        )

    def test_speaker(self, volume: int) -> None:
        self.command("AUDIO UNMUTE", lambda line: line == "OK", 2.0)
        self.command("AUDIO VOLUME 55", lambda line: line == "OK", 2.0)
        self.send("SPK BEGIN")
        ready = self.read_until(lambda line: line == "SPK READY" or line.startswith("AUDIO ERROR"), 3.0)
        if ready != "SPK READY":
            self.report("ESP32 speaker stream", False, ready or "speaker did not start")
            self.send("SPK ABORT")
            self.command(f"AUDIO VOLUME {volume}", lambda line: line == "OK")
            return

        assert self.serial is not None
        sample_rate = 16_000
        frame_samples = 320
        deadline = time.monotonic()
        for frame_no in range(35):
            frequency = 660.0 if frame_no < 18 else 880.0
            values = array.array(
                "h",
                (
                    int(4200.0 * math.sin(2.0 * math.pi * frequency * (frame_no * frame_samples + i) / sample_rate))
                    for i in range(frame_samples)
                ),
            )
            payload = base64.b64encode(values.tobytes()).decode("ascii")
            self.send("SPK:" + payload)
            deadline += 0.020
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        self.send("SPK END")
        done = self.read_until(lambda line: line == "SPK DONE" or line.startswith("AUDIO ERROR"), 3.0)
        self.command(f"AUDIO VOLUME {volume}", lambda line: line == "OK", 2.0)
        self.report(
            "ESP32 speaker stream",
            done == "SPK DONE",
            "two-tone sample completed; volume restored" if done == "SPK DONE" else (done or "no completion reply"),
        )

    def restore(self, volume: int) -> None:
        # Best-effort cleanup is deliberately independent of the test result.
        for command in (
            "MIC STOP", "SPK ABORT", "MOTOR:TOP:STOP", "MUSIC STOP",
            "TIMER STOP", "BOOK STOP", "AUDIO UNMUTE",
            f"AUDIO VOLUME {volume}", "SERVO:HEAD:95", "WAKE", "MOTOR:TOP:STOP", "NEUTRAL",
            "LOOK CENTER", "BRIGHTNESS 255",
        ):
            try:
                self.send(command)
                time.sleep(0.04)
            except Exception:
                pass


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Test AURA's connected ESP32 hardware")
    parser.add_argument("--port", default=settings.get("serial_port", "COM14"))
    parser.add_argument("--skip-motion", action="store_true", help="Do not move the head servo or top motor")
    args = parser.parse_args()
    volume = int(settings.get("speaker_volume", 75))

    print("AURA ROBOT SELF-TEST")
    print(f"Port: {args.port} at 921600 baud")
    print("The display will change, the head/propeller may move, and a short tone will play.\n")
    test = AuraSerialTest(args.port)
    try:
        test.open()
        test.test_serial_and_face()
        if args.skip_motion:
            test.skip("Head servo and top motor", "skipped by command-line option")
        else:
            test.test_motion()
        test.test_microphone()
        test.test_speaker(volume)
        test.skip("Touch gestures", "tap, multi-tap, slide and one-second hold need a human finger")
    except Exception as exc:
        test.report("Self-test execution", False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            test.restore(volume)
        finally:
            test.close()

    passed = sum(item.state == "PASS" for item in test.results)
    failed = sum(item.state == "FAIL" for item in test.results)
    manual = sum(item.state == "MANUAL" for item in test.results)
    print(f"\nSUMMARY: {passed} passed, {failed} failed, {manual} manual check(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
