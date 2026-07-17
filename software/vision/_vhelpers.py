"""Shared test helpers for detector tests."""
import time
from core.event_bus import EventBus
from vision.frame_buffer import FrameBuffer, Frame

def collect(bus):
    seen = []
    bus.subscribe_all(lambda e: seen.append((e.type, e.data)))
    return seen

def push_frame(buf, index, w=640, h=480):
    buf.push(Frame(data=f"f{index}", index=index, timestamp=time.monotonic(),
                   width=w, height=h, camera_id=0))

def wait_until(pred, timeout_s=2.0, interval=0.004):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if pred(): return True
        time.sleep(interval)
    return pred()
