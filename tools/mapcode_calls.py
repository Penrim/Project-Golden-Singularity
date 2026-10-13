"""List engine functions called from map code (BL targets outside the map code blob)."""
import struct, sys
from collections import Counter
sys.path.insert(0, ".")
from gsfs import Rom

LOAD = 0x02008000

def map_code_indices(rom):
    out = []
    for i in range(len(rom.entries)):
        s, _ = rom.file_span(i)
        if rom.data[s] not in (0, 1):
            continue
        try:
            d = rom.decompressed(i)
        except Exception:
            continue
        if d[:4] == b"\x00\x4c\x20\x47":
            out.append(i)
    return out

def normalise_bls(d):
    """Stored map code keeps BLs in 'absolute' form; convert to normal relative BLs (randomiser convertBranchLinks)."""
    d = bytearray(d)
    i = 2
    while i < len(d) - 1:
        lo = struct.unpack_from("<H", d, i)[0]
        i += 2
        if lo & 0xF800 != 0xF800:
            continue
        hi = struct.unpack_from("<H", d, i - 4)[0]
        if hi & 0xF800 != 0xF000:
            continue
        v = (((hi & 0x7FF) << 11) | (lo & 0x7FF)) << 1
        v -= (i - 2)
        struct.pack_into("<H", d, i - 4, 0xF000 | ((v >> 12) & 0x7FF))
        struct.pack_into("<H", d, i - 2, 0xF800 | ((v >> 1) & 0x7FF))
    return bytes(d)

def external_calls(d):
    d = normalise_bls(d)
    calls = Counter()
    for i in range(0, len(d) - 3, 2):
        hi, lo = struct.unpack_from("<HH", d, i)
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            off = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
            if off & 0x400000:
                off -= 0x800000
            tgt = LOAD + i + 4 + off
            if not (LOAD <= tgt < LOAD + len(d)):
                calls[tgt] += 1
    return calls

if __name__ == "__main__":
    for path in sys.argv[1:]:
        rom = Rom(path)
        idx = map_code_indices(rom)
        total = Counter()
        for i in idx:
            total.update(external_calls(rom.decompressed(i)).keys())
        print(f"== {rom.code}: {len(idx)} map code files, MFT {idx[0]}..{idx[-1]}")
        print(f"   {len(total)} distinct external call targets")
        print("   top:", [(hex(a), n) for a, n in total.most_common(12)])
        ranges = Counter(hex(a >> 16 << 16) for a in total)
        print("   by 64K region:", dict(ranges))
