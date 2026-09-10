"""Check speaker packet delivery with microphone and face commands active."""
import re
import time
from core.event_bus import EventBus
from hardware.hardware_manager import HardwareManager
from hardware.hardware_config import HardwareConfig
from hardware.serial_manager import PySerialTransport
from hardware.device_types import CommandPriority
from speech.tts_manager import Pyttsx3Engine
from speech.voice_profiles import DEFAULT_PROFILES
from speech.audio_player import Esp32AudioSink


class ObservedTransport(PySerialTransport):
    def __init__(self):
        super().__init__()
        self.sent_frames = 0
        self.stats = ''

    def write_line(self, line):
        super().write_line(line)
        if line.startswith('SPK:'):
            self.sent_frames += 1

    def read_line(self):
        line = super().read_line()
        if line and line.startswith('AUDIO STATS '):
            self.stats = line
        return line


def main():
    transport = ObservedTransport()
    cfg = HardwareConfig()
    cfg.serial.port = 'COM14'
    cfg.serial.baud_rate = 921600
    cfg.serial.read_timeout_s = .08
    cfg.health.enabled = False
    hw = HardwareManager(EventBus(), cfg, transport)
    hw.initialize()
    hw.start()
    try:
        time.sleep(2.8)
        assert hw._serial.connected
        hw.audio_link.stop_microphone()
        hw.audio_link.set_volume(75)

        def stats(expected):
            transport.stats = ''
            hw.send_face_command('AUDIO STATS', priority=CommandPriority.HIGH)
            deadline = time.monotonic() + 2
            while not transport.stats and time.monotonic() < deadline:
                time.sleep(.01)
            print(transport.stats, 'EXPECTED_FRAMES=', expected, flush=True)
            fields = dict(re.findall(r'(\w+)=(\d+)', transport.stats))
            assert int(fields['FRAMES']) == expected
            assert int(fields['QUEUE_DROPS']) == 0
            assert int(fields['WRITE_ERRORS']) == 0

        # A clip shorter than the prebuffer must finish, not deadlock.
        assert hw.audio_link.play_pcm(bytes(640), lambda: False)
        stats(1)

        # An aborted short stream must mute and discard the prebuffer.
        checks = iter([False, True])
        assert not hw.audio_link.play_pcm(bytes(1280), lambda: next(checks))
        stats(1)

        hw.audio_link.start_microphone()
        hw.set_emotion('HAPPY')
        clip = Pyttsx3Engine().synthesize(
            'Hello Kavy. This is the buffered speaker test. '
            'The microphone is listening while I speak. '
            'Please check whether this sentence sounds clear and loud enough.',
            DEFAULT_PROFILES['assistant'])
        before = transport.sent_frames
        assert Esp32AudioSink(hw.audio_link).play(clip.audio, clip.duration_s, lambda: False)
        stats(transport.sent_frames - before)
        for _ in range(10):
            assert len(hw.audio_link.read_microphone_frame(.8)) == 640
        print('MICROPHONE STILL STREAMING: PASS', flush=True)
    finally:
        if hw._serial.connected:
            hw.audio_link.stop_microphone()
            hw.audio_link.set_volume(75)
            hw.set_emotion('NORMAL')
            time.sleep(.2)
        hw.stop()


if __name__ == '__main__':
    main()
