"""Chapter-change test: GS1 "after the credits" -> clear save -> chapter card -> TLA new game with imported party.

Boots the merged ROM with an empty save, plays into the Vale field, simulates the end of the credits
(u16 0x02000402 = 2, warp to map 1) and saves that moment as the demo state. Then renames Isaac to "Alex",
lets the transition run and checks that TLA's RAM holds the imported name and that bank 1 holds GS1 clear data.

Usage: python test_transition.py MERGED.gba OUTDIR [DEMO_STATE.ss1]
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from difftest import default_script
from PIL import Image

TEST_NAME = b"Alex"


def main(rom, out, demo=None):
    os.makedirs(out, exist_ok=True)
    sav = os.path.splitext(rom)[0] + ".sav"
    if os.path.exists(sav):
        os.remove(sav)
    e = Emu.launch(rom); e.sock.settimeout(30); e.cmd("reset")
    e.to_menu(); e.press("A", after=30)                          # empty cartridge: Chapter 1 is selected
    for keys, frames in default_script():
        e.keys(*keys); e.wait(frames)
    e.keys()
    for _ in range(6):
        e.press("B", after=15)
    e.wait(30)
    e.w16(0x02000402, 2); e.w16(0x02000400, 1); e.w16(0x02030170, 1)   # GS1 right after the credits
    if demo:
        e.save(demo)
        print("demo state:", demo)

    ram = bytearray(e.rr(0x02000000, 0x2000))
    locs = [m.start() for m in re.finditer(b"Isaac", ram)]
    print("GS1 'Isaac' at", [hex(0x02000000 + l) for l in locs])
    for l in locs:                                              # rename (same length, zero-padded)
        for i, c in enumerate(TEST_NAME + b"\0"):
            e.w8(0x02000000 + l + i, c)

    shots = []
    for k, frames in enumerate((120, 120, 160, 300)):          # clear save, chapter card, TLA naming screen
        e.wait(frames)
        p = os.path.join(out, f"t{k}.png"); e.shot(p); shots.append(p)
    for _ in range(10):                                         # confirm Felix's name -> automatic import
        e.press("A", after=10); e.wait(50)
    p = os.path.join(out, "t_after.png"); e.shot(p); shots.append(p)
    tla = e.rr(0x02000000, 0x40000)
    code = e.rr(0x080000AC, 4)
    e.close()

    found = [hex(0x02000000 + m.start()) for m in re.finditer(TEST_NAME, tla)][:8]
    print("running game code", code, "| TLA RAM", TEST_NAME, "at", found)
    d = open(sav, "rb").read()
    bank1 = [s for s in range(16) if any(x != 0xFF for x in d[0x10000 + s * 0x1000:0x10000 + (s + 1) * 0x1000])]
    print("bank 1 (GS1) sectors after the transition:", bank1)
    print("RESULT:", "PASS" if found and bank1 else "FAIL")

    c = Image.new("RGB", (240 * 3, 160 * 2))
    for i, p in enumerate(shots):
        c.paste(Image.open(p), (240 * (i % 3), 160 * (i // 3)))
    c.save(os.path.join(out, "transition_sheet.png"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
