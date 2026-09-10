from vision.face_follower import FaceFollower, FacePosition


class FakeBackend:
    def __init__(self):
        self.opened = False

    def open(self):
        self.opened = True

    def read(self):
        return None

    def close(self):
        self.opened = False

    def is_open(self):
        return self.opened


def test_tracks_and_smooths_largest_face_position():
    commands = []
    follower = FaceFollower(
        FakeBackend(),
        lambda x, y: commands.append((x, y)),
        smoothing=1.0,
    )
    follower.initialize()
    follower._process(FacePosition(0.5, -0.2), now=1.0)
    assert commands == [(0.575, -0.22)]
    assert follower.health_check()


def test_recenters_once_after_face_is_lost():
    commands = []
    follower = FaceFollower(
        FakeBackend(),
        lambda x, y: commands.append((x, y)),
        smoothing=1.0,
        lost_timeout_s=1.0,
    )
    follower.initialize()
    follower._process(FacePosition(-0.5, 0.1), now=1.0)
    follower._process(None, now=2.1)
    follower._process(None, now=3.0)
    assert commands[-1] == (0.0, 0.0)
    assert commands.count((0.0, 0.0)) == 1


def test_optional_camera_mirroring():
    commands = []
    follower = FaceFollower(
        FakeBackend(),
        lambda x, y: commands.append((x, y)),
        smoothing=1.0,
        mirror_x=True,
    )
    follower.initialize()
    follower._process(FacePosition(0.4, 0.0), now=1.0)
    assert commands[-1][0] < 0.0
