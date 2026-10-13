"""Compare engine jump tables (stub = ldr r4,[pc]; bx r4; .word fn) between GS1 and TLA, slot by slot."""
import struct, sys
from difflib import SequenceMatcher
sys.path.insert(0, ".")
from gsfs import Rom

STUB = b"\x00\x4c\x20\x47"

def slots(rom, idx):
    base = rom.entries[idx]
    out = []
    o = 0
    while rom.data[base + o:base + o + 4] == STUB:
        out.append(struct.unpack_from("<I", rom.data, base + o + 4)[0])
        o += 8
    return out

def shape(rom, fn, n=48):
    """Instruction 'shape' of a Thumb function: opcode classes without immediates/offsets."""
    off = (fn & ~1) - 0x08000000
    if not (0 <= off < len(rom.data) - 2 * n):
        return ()
    hs = struct.unpack_from(f"<{n}H", rom.data, off)
    out = []
    for h in hs:
        if h & 0xF800 in (0xF000, 0xF800): out.append(0xF000)       # BL halves
        elif h & 0xF800 == 0x4800: out.append(0x4800 | (h & 0x0700)) # ldr rX,[pc]
        elif h & 0xF000 == 0xD000: out.append(h & 0xFF00)            # bcond
        elif h & 0xF800 == 0xE000: out.append(0xE000)                # b
        else: out.append(h)
        if h & 0xFF00 == 0xBD00 or h == 0x4770: break               # pop {..pc} / bx lr
    return tuple(out)

if __name__ == "__main__":
    g = Rom(sys.argv[1]); t = Rom(sys.argv[2])
    for idx in [0, 3, 4, 5, 6, 8, 10, 11]:
        sg, st = slots(g, idx), slots(t, idx)
        scores = []
        for k in range(min(len(sg), len(st))):
            a, b = shape(g, sg[k]), shape(t, st[k])
            scores.append(SequenceMatcher(None, a, b).ratio() if a and b else 0)
        good = sum(s >= 0.8 for s in scores); mid = sum(0.5 <= s < 0.8 for s in scores)
        print(f"file {idx:3d}: GS1 {len(sg):3d} slots, TLA {len(st):3d} slots | same-ish(>=.8) {good}, partial {mid}, different {len(scores)-good-mid}")
