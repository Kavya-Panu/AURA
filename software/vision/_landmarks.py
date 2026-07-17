"""Builders producing FaceMesh/Hand landmark sets with known geometry."""

def _blank(n=478):
    return [(0.5, 0.5)] * n

def face_mesh_smiling():
    """Wide mouth, closed lips -> high smile ratio."""
    pts = _blank()
    pts[33] = (0.35, 0.5); pts[263] = (0.65, 0.5)      # eyes (dist 0.30)
    pts[61] = (0.33, 0.6); pts[291] = (0.67, 0.6)      # very wide mouth
    pts[13] = (0.5, 0.6); pts[14] = (0.5, 0.605)       # lips nearly closed
    return pts

def face_mesh_neutral():
    pts = _blank()
    pts[33] = (0.35, 0.5); pts[263] = (0.65, 0.5)
    pts[61] = (0.44, 0.6); pts[291] = (0.56, 0.6)      # narrow mouth
    pts[13] = (0.5, 0.59); pts[14] = (0.5, 0.61)
    return pts

def face_mesh_head(nose_x=0.5, nose_y=0.5):
    """Head with configurable nose position within the face box."""
    pts = _blank()
    pts[234] = (0.3, 0.5); pts[454] = (0.7, 0.5)       # face left/right edges
    pts[10] = (0.5, 0.3); pts[152] = (0.5, 0.7)        # forehead/chin
    pts[1] = (nose_x, nose_y)                          # nose tip
    return pts

def face_mesh_gaze(centered=True):
    """Iris centered (looking at camera) or shifted (looking away)."""
    pts = _blank()
    # left eye outer=33 inner=133, iris=468 ; right inner=362 outer=263 iris=473
    pts[33] = (0.30, 0.5); pts[133] = (0.40, 0.5)
    pts[362] = (0.60, 0.5); pts[263] = (0.70, 0.5)
    if centered:
        pts[468] = (0.35, 0.5); pts[473] = (0.65, 0.5)  # mid of each eye
    else:
        pts[468] = (0.395, 0.5); pts[473] = (0.695, 0.5)  # shifted to inner/outer
    return pts

def hand_thumbs_up():
    """Thumb tip above joints; other fingers curled (tips below pips)."""
    pts = [(0.5, 0.9)] * 21
    pts[0] = (0.5, 0.9)
    pts[2] = (0.5, 0.7); pts[3] = (0.5, 0.6); pts[4] = (0.5, 0.5)  # thumb up
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        pts[pip] = (0.5, 0.7); pts[tip] = (0.5, 0.8)   # tip below pip (curled)
    return pts

def hand_raised():
    """All fingers extended (tips above pips)."""
    pts = [(0.5, 0.9)] * 21
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        pts[pip] = (0.5, 0.6); pts[tip] = (0.5, 0.4)   # tip above pip (extended)
    return pts

def hand_at(x):
    """A hand whose wrist is at horizontal position x (for wave detection)."""
    pts = [(x, 0.5)] * 21
    return pts
