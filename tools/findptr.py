"""Find where an unrelocated pointer value (or a base just below it) is stored in the original ROM."""
import struct, sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from gsfs import Rom
from reloc import analyse

def find(rom, relocs, value, window=0x400):
    d = rom.data
    out = []
    for o in range(0, len(d) - 3, 4):
        w = struct.unpack_from("<I", d, o)[0]
        if value - window <= w <= value:
            out.append((o, w, o in relocs))
    return out

if __name__ == "__main__":
    r = Rom(sys.argv[1]); rel = set(analyse(r, 0x320000)[0])
    for v in sys.argv[2:]:
        v = int(v, 16)
        print(f"== {v:#x}")
        for o, w, ok in find(r, rel, v)[:20]:
            print(f"   @{o:#08x} = {w:#010x} {'(relocated)' if ok else 'NOT relocated'}  ctx {r.data[o-8:o+12].hex(' ')}")
