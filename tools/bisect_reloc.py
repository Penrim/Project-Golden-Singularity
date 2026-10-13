"""Bisect heuristic relocations to find the word(s) whose relocation breaks a given map.

Builds GS1-relocated test ROMs with a subset of heuristic relocations reverted and checks whether warping to
MAP crashes. Usage: python bisect_reloc.py GS1.gba MAP
"""
import os, socket, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_gs1_reloc as B
from gsfs import Rom
from reloc import analyse, literal_targets, is_ptr
from emu import Emu
import maptour

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "bisect")


def heuristic_set(g):
    rel, _ = analyse(g, g.mft_off)
    d, size = g.data, len(g.data)
    lits = {a for a in literal_targets(d, 0, g.mft_off)
            if a % 4 == 0 and is_ptr(struct.unpack_from("<I", d, a)[0], size)}
    mft = {g.mft_off + 4 * i for i in range(len(g.entries))}
    return sorted(set(rel) - lits - mft)


def crashes(gs1, revert, m, tag):
    base, _ = B.build(gs1, None)
    out = bytearray(base)
    for a in revert:  # undo relocation of these words
        o = B.SHIFT + a
        w = struct.unpack_from("<I", out, o)[0]
        if w >= 0x09000000:
            struct.pack_into("<I", out, o, w - B.SHIFT)
    rom = os.path.join(OUT, f"{tag}.gba")
    open(rom, "wb").write(out)
    state = maptour.field_state(rom, os.path.join(OUT, "field.ss"), False)
    e = Emu.launch(rom); e.sock.settimeout(10)
    try:
        e.load(state); e.wait(2)
        e.w16(maptour.MAP_VAR, m); e.w16(maptour.WARP_TRIGGER, 1)
        for _ in range(20):
            e.wait(20)
            pc = int(e.cmd("pc"))
            if not (pc < 0x4000 or 0x02000000 <= pc < 0x04000000 or 0x09000000 <= pc < 0x09800000):
                return True
        return False
    except (socket.timeout, OSError):
        return True
    finally:
        e.close()


if __name__ == "__main__":
    gs1, m = sys.argv[1], int(sys.argv[2])
    os.makedirs(OUT, exist_ok=True)
    g = Rom(gs1)
    cand = heuristic_set(g)
    print("heuristic candidates:", len(cand))
    assert crashes(gs1, [], m, "base"), "map does not crash with full relocation"
    assert not crashes(gs1, cand, m, "none"), "still crashes with all heuristics reverted"
    lo = cand
    step = 0
    while len(lo) > 1:
        half = lo[:len(lo) // 2]
        step += 1
        if not crashes(gs1, half, m, f"s{step}"):
            lo = half          # reverting this half fixes it -> culprit inside
        else:
            lo = lo[len(lo) // 2:]
        print(f"step {step}: {len(lo)} candidates left ({lo[0]:#x}..{lo[-1]:#x})")
    a = lo[0]
    print(f"culprit word at GS1 offset {a:#x} = {struct.unpack_from('<I', g.data, a)[0]:#x}")
    print("context:", g.data[a - 16:a + 16].hex(" "))
