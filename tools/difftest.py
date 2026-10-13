"""Differential test: play two ROMs with the same scripted inputs, compare screenshots, log stray ROM reads.

Usage: python difftest.py ORIGINAL.gba TEST.gba OUTDIR [script]
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from PIL import Image, ImageChops

# (keys, frames) steps. A long mash through intro/title/naming into gameplay, then some walking.
def default_script():
    s = [((), 300)]
    for k in range(60):
        s += [(("START",) if k % 3 == 0 else ("A",), 6), ((), 54)]
    for d in ("DOWN", "LEFT", "UP", "RIGHT") * 4:
        s += [((d,), 40), (("A",), 6), ((), 30)]
    for k in range(40):
        s += [(("A",), 6), ((), 40)]
    return s


def run(rom, outdir, script, shot_every=240, watch=None):
    for sav in glob.glob(os.path.splitext(rom)[0] + ".sav"):
        os.remove(sav)
    os.makedirs(outdir, exist_ok=True)
    e = Emu.launch(rom)
    e.sock.settimeout(30)
    e.cmd("reset")  # align both runs to power-on
    try:
        if watch:
            e.watch(*watch)
        t, next_shot, shots, hits = 0, 0, [], {}
        for keys, frames in script:
            try:
                e.keys(*keys)
                e.wait(frames)
            except OSError:
                print(f"  !! {os.path.basename(rom)}: emulator stopped responding around frame {t}")
                break
            t += frames
            if t >= next_shot:
                p = os.path.join(outdir, f"{t:06d}.png"); e.shot(p); shots.append(p)
                next_shot = t + shot_every
            if watch:
                for pc, (n, regs) in e.hits().items():
                    c, r = hits.get(pc, (0, regs)); hits[pc] = (c + n, r)
        return shots, hits
    finally:
        e.close()


def same(a, b):
    return ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB")).getbbox() is None


if __name__ == "__main__":
    orig, test, out = sys.argv[1:4]
    script = default_script()
    sa, _ = run(orig, os.path.join(out, "orig"), script)
    sb, hits = run(test, os.path.join(out, "test"), script, watch=(0x08000100, 0x08FFFFFF))
    first_diff = next((os.path.basename(a) for a, b in zip(sa, sb) if not same(a, b)), None)
    print("screenshots:", len(sa), "first difference at frame:", first_diff)
    diffs = [os.path.basename(a) for a, b in zip(sa, sb) if not same(a, b)]
    print("differing screenshots:", len(diffs), "of", min(len(sa), len(sb)), diffs[:8])
    print("stray reads of old GS1 area:", len(hits))
    for pc, (n, regs) in sorted(hits.items()):
        print(f"  pc={pc:08x} x{n}  {regs}")
