"""Small helpers for scripted play: detect dialogue boxes / menus from screenshots and act accordingly."""
import os
from PIL import Image

WINDOW_BLUE = (0, 99, 132)       # Golden Sun window fill colour


def _is_blue(px):
    return abs(px[0] - WINDOW_BLUE[0]) < 12 and abs(px[1] - WINDOW_BLUE[1]) < 12 and abs(px[2] - WINDOW_BLUE[2]) < 12


def window_share(img, box):
    """Fraction of window-blue pixels in box (x0, y0, x1, y1), sampled every 4 px."""
    x0, y0, x1, y1 = box
    n = hit = 0
    for y in range(y0, y1, 4):
        for x in range(x0, x1, 4):
            n += 1
            hit += _is_blue(img.getpixel((x, y)))
    return hit / max(n, 1)


def screen_state(e, path):
    """'menu' (full-screen menu), 'dialog' (text box at top), or 'field'."""
    e.shot(path)
    img = Image.open(path).convert("RGB")
    if window_share(img, (0, 40, 240, 160)) > 0.35:
        return "menu"
    if window_share(img, (88, 140, 160, 156)) > 0.05 and window_share(img, (184, 2, 236, 24)) > 0.15:
        return "menu"                       # field menu: icon bar + status box
    if window_share(img, (40, 4, 200, 30)) > 0.25 or window_share(img, (40, 120, 200, 156)) > 0.25:
        return "dialog"
    return "field"


def step(e, direction, tmp, hold=24):
    """One scripted step: close menus, advance dialogue, otherwise walk."""
    st = screen_state(e, tmp)
    if st == "menu":
        e.press("B", after=20)
    elif st == "dialog":
        e.press("A", hold=3, after=25)
    else:
        e.keys(direction); e.wait(hold); e.keys(); e.wait(4)
    return st


def run_cutscene(e, tmp, idle_frames=240, max_steps=400):
    """Advance dialogue until the game has been idle (no dialogue / menu) for `idle_frames`."""
    idle = 0
    for _ in range(max_steps):
        st = screen_state(e, tmp)
        if st == "dialog":
            e.press("A", hold=3, after=25); idle = 0
        elif st == "menu":
            e.press("B", after=20); idle = 0
        else:
            e.wait(30); idle += 30
            if idle >= idle_frames:
                return True
    return False
