"""FaceTracker: IDs, normalized position, smoothing, FACE_TRACKED/FACE_POSITION."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision.face_tracker import FaceTracker
from vision.tests._vhelpers import collect

def face_event(bus, faces, w=640, h=480, idx=0):
    bus.emit(RobotEvent.FACE_FOUND, {
        "count": len(faces),
        "faces": [{"box": b, "confidence": c} for b, c in faces],
        "frame": {"width": w, "height": h}, "frame_index": idx},
        source="face")

class TestFaceTracker(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.seen = collect(self.bus)
        self.ft = FaceTracker(self.bus, smoothing=1.0)  # no smoothing lag
        self.ft.initialize(); self.ft.start()

    def tearDown(self):
        self.ft.stop()

    def test_center_face_is_zero(self):
        # face centered in 640x480 -> normalized (0,0)
        face_event(self.bus, [([320 - 30, 240 - 30, 60, 60], 0.9)])
        pos = next(d for t, d in self.seen if t == RobotEvent.FACE_POSITION)
        self.assertAlmostEqual(pos["x"], 0.0, delta=0.05)
        self.assertAlmostEqual(pos["y"], 0.0, delta=0.05)

    def test_left_face_negative_x(self):
        face_event(self.bus, [([0, 240 - 30, 60, 60], 0.9)])
        pos = next(d for t, d in self.seen if t == RobotEvent.FACE_POSITION)
        self.assertLess(pos["x"], -0.5)

    def test_right_bottom_face(self):
        face_event(self.bus, [([640 - 60, 480 - 60, 60, 60], 0.9)])
        pos = next(d for t, d in self.seen if t == RobotEvent.FACE_POSITION)
        self.assertGreater(pos["x"], 0.5)
        self.assertGreater(pos["y"], 0.5)

    def test_position_bounded(self):
        face_event(self.bus, [([2000, 2000, 60, 60], 0.9)])  # off-frame
        pos = next(d for t, d in self.seen if t == RobotEvent.FACE_POSITION)
        self.assertLessEqual(pos["x"], 1.0)
        self.assertLessEqual(pos["y"], 1.0)

    def test_tracking_id_stable_across_frames(self):
        for _ in range(3):
            face_event(self.bus, [([300, 220, 60, 60], 0.9)])
        tracked = [d for t, d in self.seen if t == RobotEvent.FACE_TRACKED]
        ids = {tr["id"] for d in tracked for tr in d["tracks"]}
        self.assertEqual(len(ids), 1)   # same face -> one stable id

    def test_two_faces_two_ids(self):
        face_event(self.bus, [([50, 220, 60, 60], 0.9),
                              ([500, 220, 60, 60], 0.9)])
        tracked = [d for t, d in self.seen if t == RobotEvent.FACE_TRACKED][-1]
        self.assertEqual(len(tracked["tracks"]), 2)

    def test_smoothing_dampens_jitter(self):
        # Isolated bus + single tracker so no other tracker's emissions leak in.
        bus = EventBus()
        seen2 = collect(bus)
        ft = FaceTracker(bus, smoothing=0.3, match_distance=0.5)
        ft.start()
        def ev(cx):
            box = [int(cx) - 30, 210, 60, 60]
            bus.emit(RobotEvent.FACE_FOUND, {
                "count": 1, "faces": [{"box": box, "confidence": 0.9}],
                "frame": {"width": 640, "height": 480}, "frame_index": 0},
                source="face")
        ev(320)          # center -> normalized x ~ 0.0 (establishes the track)
        ev(448)          # move right: cx=448 -> raw nx = 448/640*2-1 = 0.4
        positions = [d["x"] for t, d in seen2 if t == RobotEvent.FACE_POSITION]
        raw_target = 448 / 640 * 2 - 1                 # 0.4
        # same track updated via EMA(alpha=0.3): 0.7*0 + 0.3*0.4 = 0.12 << 0.4
        self.assertGreater(positions[-1], 0.0)         # it moved
        self.assertLess(positions[-1], raw_target)     # but was damped
        ft.stop()

    def test_face_lost_clears_tracks(self):
        face_event(self.bus, [([300, 220, 60, 60], 0.9)])
        self.assertEqual(self.ft.track_count, 1)
        self.bus.emit(RobotEvent.FACE_LOST, {}, source="face")
        self.assertEqual(self.ft.track_count, 0)

if __name__ == "__main__":
    unittest.main()
