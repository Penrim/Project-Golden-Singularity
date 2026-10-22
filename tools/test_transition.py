"""Chapter-change test: GS1 "after the credits" -> clear save -> chapter card -> TLA new game with imported party.

Boots the merged ROM with an empty save, plays into the Vale field, simulates the end of the credits
(u16 0x02000402 = 2, warp to map 1) and saves that moment as the demo state. Then renames Isaac to "Alex",
lets the transition run and checks that TLA's RAM holds the imported name and that bank 1 holds GS1 clear data.

The chapter card must be visible: in a real playthrough GS1's title screen (shown after the credits) leaves BG2's
affine matrix/offset scaled and moved and its fade to black (BLDCNT/BLDY) set, and mode 3 draws the card through
them (1.2.1: black screen). The simulated end of the credits skips that screen, so the test writes such leftover
values when gs1_chapter_end starts and then compares every screenshot taken in the card phase (DISPCNT = mode 3)
with the card image in the ROM (every 20 frames while the card is up).

Usage: python test_transition.py MERGED.gba OUTDIR [DEMO_STATE.ss1]
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from difftest import default_script
from PIL import Image

TEST_NAME = b"Alex"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD = 0x09B10000                                               # 240x160 BGR555 chapter card (bootmenu.py)
# Leftovers of GS1's title screen: BG2 scaled x2 with its origin off-screen, fade to black, mosaic.
TITLE_LEFTOVERS = ((0x04000020, 0x00000200), (0x04000024, 0x02000000), (0x04000028, 0x00010000),
                   (0x0400002C, 0x00010000), (0x0400004C, 0x00003333), (0x04000050, 0x000000FE),
                   (0x04000054, 0x00000010))


def chapter_end_addr(rom_data):
    """gs1_chapter_end from the precompiled runtime's symbols, checked against the ROM (the first instructions,
    ignoring pc-relative literal offsets, so that older builds of the same pair work too)."""
    pair = f"{rom_data[0x10000AC:0x10000B0].decode()}_{rom_data[0xAC:0xB0].decode()}"
    pre = os.path.join(ROOT, "cart", "prebuilt", pair)
    addr = json.load(open(os.path.join(pre, "meta.json")))["symbols"]["gs1_chapter_end"]
    off = addr - 0x09B00000
    want = open(os.path.join(pre, "runtime.bin"), "rb").read()[off:off + 16]
    have = rom_data[addr - 0x08000000:addr - 0x08000000 + 16]
    same = lambda a, b: a == b if (a >> 11) != 9 else (a >> 8) == (b >> 8)   # ldr rX,[pc,#imm]: offset may differ
    h = lambda d, i: d[i] | d[i + 1] << 8
    assert all(same(h(want, i), h(have, i)) for i in range(0, 16, 2)), f"gs1_chapter_end not found in the ROM ({pair})"
    return addr


def card_image(rom_data):
    img = Image.new("RGB", (240, 160))
    raw = rom_data[CARD - 0x08000000:CARD - 0x08000000 + 240 * 160 * 2]
    c5 = lambda v: v << 3 | v >> 2
    img.putdata([(c5(v & 31), c5(v >> 5 & 31), c5(v >> 10 & 31))
                 for v in (raw[i] | raw[i + 1] << 8 for i in range(0, len(raw), 2))])
    return img


def matches(shot, ref, tol=24):
    """Share of the card's bright pixels (sky, clouds, text) that the screenshot shows within tol per channel; a
    black screen scores about 0."""
    a, b = shot.convert("RGB").tobytes(), ref.tobytes()
    bright = [i for i in range(0, len(b), 3) if max(b[i:i + 3]) >= 64]
    return sum(all(abs(a[i + k] - b[i + k]) <= tol for k in range(3)) for i in bright) / len(bright)


def main(rom, out, demo=None):
    os.makedirs(out, exist_ok=True)
    rom_data = open(rom, "rb").read()
    hook, card = chapter_end_addr(rom_data), card_image(rom_data)
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
    hero = bytes(ram[0x500:0x50F]).split(b"\0")[0]              # Isaac's name as entered (default differs per language)
    assert hero and len(hero) >= len(TEST_NAME), hero
    locs = [m.start() for m in re.finditer(re.escape(hero), ram)]
    print(f"GS1 hero {hero!r} at", [hex(0x02000000 + l) for l in locs])
    for l in locs:                                              # rename (same length, zero-padded)
        for i, c in enumerate(TEST_NAME + b"\0"):
            e.w8(0x02000000 + l + i, c)

    e.cmd(f"bpwrite {hook} " + " ".join(f"{a} {v}" for a, v in TITLE_LEFTOVERS))

    shots, card_scores = [], []
    for step in range(1, 13):                                   # clear save, chapter card: look every 20 frames
        e.wait(20)
        if e.r16(0x04000000) & 7 == 3:                          # mode 3: the chapter card is on screen
            p = os.path.join(out, f"card{step:02}.png"); e.shot(p)
            card_scores.append(round(matches(Image.open(p), card), 3))
        if step % 6 == 0:
            p = os.path.join(out, f"t{step // 6 - 1}.png"); e.shot(p); shots.append(p)
    for k, frames in ((2, 160), (3, 300)):                      # TLA naming screen
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
    card_ok = bool(card_scores) and min(card_scores) >= 0.9
    print("chapter card shots (share of its bright pixels shown):", card_scores,
          "| visible" if card_ok else "| NOT VISIBLE")
    print("RESULT:", "PASS" if found and bank1 and card_ok else "FAIL")

    c = Image.new("RGB", (240 * 3, 160 * 2))
    for i, p in enumerate(shots):
        c.paste(Image.open(p), (240 * (i % 3), 160 * (i // 3)))
    c.save(os.path.join(out, "transition_sheet.png"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
