"""End-to-end save test on the merged ROM: save in GS1, save in TLA, check banks, reboot and check both load.

Usage: python test_saves.py build/gsmerge.gba OUTDIR
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from difftest import default_script


def boot(rom, game):
    e = Emu.launch(rom)
    e.sock.settimeout(30)
    e.cmd("reset")
    e.to_menu()
    # the menu has 2 entries (Chapter 1/2) or 3 (Continue/Chapter 1/Chapter 2) and wraps around:
    # UP once is always Chapter 2 (TLA), UP twice always Chapter 1 (GS1)
    for _ in range(1 if game == "TLA" else 2):
        e.press("UP", after=20)
    e.press("A", after=30)
    return e


def save_from_field(e, out, tag):
    for _ in range(6):
        e.press("B", after=15)
    e.wait(30)
    e.press("START", after=40)
    for k in range(4):
        e.press("A", after=60)
    e.shot(os.path.join(out, f"{tag}_saved.png"))
    e.wait(300)


def banks(sav):
    d = open(sav, "rb").read()
    out = []
    for b in range(len(d) // 0x10000):
        seg = d[b * 0x10000:(b + 1) * 0x10000]
        out.append([s for s in range(16) if any(x != 0xFF for x in seg[s * 0x1000:(s + 1) * 0x1000])])
    return d, out


def main(rom, out):
    os.makedirs(out, exist_ok=True)
    sav = os.path.splitext(rom)[0] + ".sav"
    if os.path.exists(sav):
        os.remove(sav)

    e = boot(rom, "GS1")
    for keys, frames in default_script():
        e.keys(*keys); e.wait(frames)
    e.keys()
    save_from_field(e, out, "gs1")
    e.close()
    d1, b1 = banks(sav)
    print("after GS1 save: sectors per bank", b1)

    e = boot(rom, "TLA")
    for k in range(120):
        e.press("START" if k % 4 == 0 else "A", hold=6, after=40)
    for k in range(400):
        e.press("A", hold=4, after=26)
    save_from_field(e, out, "tla")
    e.close()
    d2, b2 = banks(sav)
    print("after TLA save: sectors per bank", b2)
    print("GS1 bank untouched by TLA:", d1[0x10000:] == d2[0x10000:])

    for game in ("GS1", "TLA"):
        e = boot(rom, game)
        for k in range(12):
            e.press("START" if k % 2 == 0 else "A", hold=6, after=50)
        e.shot(os.path.join(out, f"{game.lower()}_reload.png"))
        e.close()


if __name__ == "__main__":
    main(*sys.argv[1:3])
