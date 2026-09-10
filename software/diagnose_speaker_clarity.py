"""Controlled speech comparison; close normal AURA before running."""
import time
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd
from core.event_bus import EventBus
from hardware.hardware_manager import HardwareManager
from hardware.hardware_config import HardwareConfig
from hardware.serial_manager import PySerialTransport
from speech.tts_manager import Pyttsx3Engine
from speech.voice_profiles import DEFAULT_PROFILES
from speech.audio_player import Esp32AudioSink


def main():
    cfg = HardwareConfig()
    cfg.serial.port = 'COM14'
    cfg.serial.baud_rate = 921600
    cfg.serial.read_timeout_s = .08
    cfg.health.enabled = False
    hw = HardwareManager(EventBus(), cfg, PySerialTransport())
    hw.initialize()
    hw.start()
    try:
        time.sleep(2.8)
        assert hw._serial.connected, 'Robot not connected; no test played'
        hw.audio_link.stop_microphone()
        hw.audio_link.set_volume(60)
        for label, processed, mic in [('one', True, False),
                                      ('two', False, False),
                                      ('three', False, True)]:
            clip = Pyttsx3Engine().synthesize(
                f'Test {label}. Hello Kavy. Is this voice clear and smooth?',
                DEFAULT_PROFILES['assistant'])
            path = Path(str(clip.audio))
            print(f'TEST {label}: processed={processed}, microphone={mic}', flush=True)
            try:
                if mic:
                    hw.audio_link.start_microphone()
                if processed:
                    result = Esp32AudioSink(hw.audio_link).play(
                        clip.audio, clip.duration_s, lambda: False)
                else:
                    samples, rate = sf.read(path, dtype='float32', always_2d=True)
                    mono = samples.mean(axis=1)
                    mono -= mono.mean()
                    divisor = gcd(rate, 16000)
                    mono = resample_poly(mono, 16000//divisor, rate//divisor)
                    peak = float(np.max(np.abs(mono)))
                    print(f'Unprocessed peak={peak:.3f}', flush=True)
                    mono *= min(1., .4/max(peak, 1e-6))
                    mono = np.concatenate((np.zeros(3200), mono, np.zeros(1600)))
                    pcm = (mono * 32767).astype('<i2').tobytes()
                    result = hw.audio_link.play_pcm(pcm, lambda: False)
                print('PLAYBACK COMPLETE:', result, flush=True)
            finally:
                # Only this test's generated temporary speech file is removed.
                path.unlink(missing_ok=True)
                hw.audio_link.stop_microphone()
            time.sleep(2)
    finally:
        if hw._serial.connected:
            hw.audio_link.stop_microphone()
            hw.audio_link.set_volume(75)
        hw.stop()


if __name__ == '__main__':
    main()
