"""USB timeout/packet boundaries must never become audio-line boundaries."""
from collections import deque
import base64

from hardware.serial_manager import PySerialTransport


class UsbPackets:
    def __init__(self, packets):
        self.packets = deque(packets)
        self.read_sizes = []

    @property
    def in_waiting(self):
        return len(self.packets[0]) if self.packets else 0

    def read(self, size):
        self.read_sizes.append(size)
        return self.packets.popleft() if self.packets else b""

    def close(self):
        pass


def test_timeout_preserves_split_microphone_frame():
    pcm = bytes(i % 251 for i in range(640))
    line = b"MIC:" + base64.b64encode(pcm) + b"\n"
    transport = PySerialTransport()
    transport._serial = UsbPackets([line[:300], b"", line[300:]])
    assert transport.read_line() is None
    assert transport.read_line() is None
    result = transport.read_line()
    assert base64.b64decode(result[4:], validate=True) == pcm
    assert transport._serial.read_sizes[0] == 300


def test_multiple_replies_in_one_usb_packet_are_delivered_in_order():
    transport = PySerialTransport()
    transport._serial = UsbPackets([b"SPK DONE\r\nMIC BEGIN 16000 320\nPONG\n"])
    assert transport.read_line() == "SPK DONE"
    assert transport.read_line() == "MIC BEGIN 16000 320"
    assert transport.read_line() == "PONG"


def test_disconnect_does_not_join_old_partial_reply_to_new_session():
    transport = PySerialTransport()
    transport._serial = UsbPackets([b"MIC:abc"])
    assert transport.read_line() is None
    transport.close()
    transport._serial = UsbPackets([b"PONG\n"])
    assert transport.read_line() == "PONG"


def test_oversized_unterminated_line_is_discarded_then_recovers():
    transport = PySerialTransport()
    transport._serial = UsbPackets([b"x" * 4096] * 5 + [b"tail\nPONG\n"])
    for _ in range(5):
        assert transport.read_line() is None
    assert transport.read_line() == "PONG"
