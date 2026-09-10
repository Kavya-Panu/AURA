from __future__ import annotations

import array
import math


def silence_frame(samples: int) -> bytes:
    return array.array("h", [0] * samples).tobytes()


def tone_frame(samples: int, amplitude: int = 9000) -> bytes:
    values = [
        int(amplitude * math.sin(2.0 * math.pi * 440.0 * i / 16000.0))
        for i in range(samples)
    ]
    return array.array("h", values).tobytes()
