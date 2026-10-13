"""Find long runs of consecutive ROM pointers (candidate Master File Table)."""
import struct, sys

def runs(rom, min_len=500):
    size = len(rom)
    out = []
    i = 0
    n = size // 4
    words = struct.unpack_from(f"<{n}I", rom)
    start = None
    for k, w in enumerate(words):
        ok = 0x08000000 <= w < 0x08000000 + size
        if ok and start is None:
            start = k
        elif not ok and start is not None:
            if k - start >= min_len:
                out.append((start * 4, k - start))
            start = None
    return out

for path in sys.argv[1:]:
    rom = open(path, "rb").read()
    print("==", path)
    for off, cnt in runs(rom):
        print(f"  0x{off:07X}  {cnt} pointers")
