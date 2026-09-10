from __future__ import annotations

import base64

from hardware.esp32_audio import Esp32AudioLink
from voice.backends import Esp32SerialMicrophone


class LoopbackSerial:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.link: Esp32AudioLink | None = None

    def send_immediate(self, line: str) -> bool:
        self.lines.append(line)
        assert self.link is not None
        if line == "AUDIO INFO":
            self.link.handle_line("AUDIO READY RATE=16000 FRAME=320 CODEC=ES8311")
        elif line == "MIC START":
            self.link.handle_line("MIC BEGIN 16000 320")
        elif line == "MIC STOP":
            self.link.handle_line("MIC END")
        elif line == "SPK BEGIN":
            self.link.handle_line("SPK READY")
        elif line == "SPK END":
            self.link.handle_line("SPK DONE")
        return True


def build_link() -> tuple[Esp32AudioLink, LoopbackSerial]:
    serial = LoopbackSerial()
    link = Esp32AudioLink(serial)  # type: ignore[arg-type]
    serial.link = link
    return link, serial


def test_probe_and_microphone_frame() -> None:
    link, _serial = build_link()
    assert link.probe(0.1)

    microphone = Esp32SerialMicrophone(link)
    microphone.open()
    pcm = bytes(640)
    assert link.handle_line("MIC:" + base64.b64encode(pcm).decode("ascii"))
    assert microphone.read_frame() == pcm
    microphone.close()


def test_short_microphone_chunks_are_reassembled_without_audio_loss() -> None:
    link, _serial = build_link()
    microphone = Esp32SerialMicrophone(link)
    microphone.open()

    pcm = bytes((index % 251 for index in range(640)))
    first = pcm[:592]
    second = pcm[592:]
    assert link.handle_line("MIC:" + base64.b64encode(first).decode("ascii"))
    assert link.handle_line("MIC:" + base64.b64encode(second).decode("ascii"))
    assert microphone.read_frame() == pcm
    microphone.close()


def test_multiple_short_chunks_are_normalized_to_640_byte_frames() -> None:
    link, _serial = build_link()
    microphone = Esp32SerialMicrophone(link)
    microphone.open()

    pcm = bytes((index % 239 for index in range(1280)))
    chunks = (pcm[:544], pcm[544:1136], pcm[1136:])
    for chunk in chunks:
        assert link.handle_line(
            "MIC:" + base64.b64encode(chunk).decode("ascii")
        )
    assert microphone.read_frame() == pcm[:640]
    assert microphone.read_frame() == pcm[640:]
    microphone.close()


def test_speaker_stream_is_framed_and_closed() -> None:
    link, serial = build_link()
    assert link.play_pcm(bytes(640), lambda: False)
    assert serial.lines[0] == "AUDIO UNMUTE"
    assert serial.lines[1] == "SPK BEGIN"
    assert serial.lines[2].startswith("SPK:")
    assert serial.lines[-1] == "SPK END"
