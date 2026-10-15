"""Code-shape proofs for three small UI tables whose words the relocation heuristics can take for pointers. Each table
is found by the code that reads it (version-independent byte patterns), so its bounds come from that code:

  menu font      `ldr rT,=T; subs rA,#0x20; subs rB,#0x20; lsls rA,rA,#5; lsls rB,rB,#5; ldrh rA,[rT,rA]`
                 (USA 0x08016E16): 32-byte glyph records {u16 width, bitmap} indexed by char - 0x20. Chars are
                 bytes (0x20..0xFF), so at most 224 records; the table must end before the next code-referenced
                 address. Extra check: in no 4-byte column of the records do more than a few values look like ROM
                 addresses (a pointer field would hold one in every record).
  credits font   `movs r2,#0x20; rsbs r2,r2,#0; adds r2,r2,r0` (r0 = char read with ldrb, 0 ends, <= 0x1F control)
                 then `ldr rT,=T; lsls rX,r2,#3; adds rY,rT,rX` and `ldrb [rY]` row reads (USA 0x080F08C6): 8-byte
                 1-bit glyphs, char - 0x20 with a byte char -> at most 224 * 8 bytes.
  cursor offsets `movs r1,#N; bl MOD; ...; ldrb rX,[rT,r0]` (USA 0x080192E8) where MOD jumps to the IWRAM division
                 routine that returns the remainder (`mov ip,lr; bl div; mov r0,r1; bx ip`): a byte table of
                 exactly N entries.

  python fontproof.py GS1.gba        -> prints the tables and how many pointer-like words they hold
"""
import bisect, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles

ROM = 0x08000000


def u16(d, a):
    return d[a] | d[a + 1] << 8


def u32(d, a):
    return struct.unpack_from("<I", d, a)[0]


def lit(d, h):
    """(literal offset, value) of the Thumb `ldr rN,[pc,#imm]` at h, else None."""
    ins = u16(d, h)
    if ins & 0xF800 != 0x4800:
        return None
    la = ((h + 4) & ~3) + (ins & 0xFF) * 4
    return (la, u32(d, la)) if la + 4 <= len(d) else None


def code_labels(d, end):
    """Sorted ROM offsets that code loads as literals (anything referenced from code starts a new object)."""
    out = set()
    for h in range(0, end, 2):
        x = lit(d, h)
        if x and ROM <= x[1] < ROM + len(d):
            out.add(x[1] - ROM)
    return sorted(out)


def next_label(labels, T):
    k = bisect.bisect_right(labels, T)
    return labels[k] if k < len(labels) else None


def menu_font(d, end):
    """Table offsets T of the menu-font reader shape (see module doc)."""
    out = {}
    for h in range(0, end - 12, 2):
        x = lit(d, h)
        if not x:
            continue
        rt = (u16(d, h) >> 8) & 7
        a, b, c, e, f = (u16(d, h + 2 * k) for k in range(1, 6))
        if (a & 0xF8FF == 0x3820 and b & 0xF8FF == 0x3820 and c & 0xFFC0 == 0x0140 and e & 0xFFC0 == 0x0140
                and f & 0xFE00 == 0x5A00 and (f >> 3) & 7 == rt):           # subs #0x20 x2, lsls #5 x2, ldrh [rT,rM]
            out.setdefault(x[1] - ROM, h)
    return out


def credits_font(d, end):
    out = {}
    pre = bytes.fromhex("2022") + bytes.fromhex("5242") + bytes.fromhex("1218")    # movs r2,#0x20; rsbs; adds r2,r2,r0
    p = d.find(pre, 0, end)
    while p >= 0:
        for h in range(p + 6, p + 16, 2):
            x = lit(d, h)
            if not x:
                continue
            rt = (u16(d, h) >> 8) & 7
            s, ad = u16(d, h + 2), u16(d, h + 4)
            if s & 0xFFF8 == 0x00D0:                                                   # lsls rX, r2, #3
                rx = s & 7
                if ad & 0xFE00 == 0x1800 and {(ad >> 3) & 7, (ad >> 6) & 7} == {rt, rx}:          # adds rY, rT, rX
                    ry = ad & 7
                    for k in range(3, 24):                                                       # ldrb rZ, [rY]
                        if u16(d, h + 2 * k) & 0xFFF8 == 0x7800 | ry << 3:
                            out.setdefault(x[1] - ROM, h)
                            break
        p = d.find(pre, p + 1, end)
    return out


def remainder_veneers(d, iwram):
    """ROM offsets of `ldr r3,[pc,#0]; bx r3; .word F` veneers whose IWRAM target F starts with
    mov ip,lr; bl div; mov r0,r1; bx ip (the remainder of the division routine)."""
    out = set()
    lma, vma, size = iwram["iwram_src"] - ROM, 0x03000000, iwram["iwram_bytes"]
    p = d.find(bytes.fromhex("004b1847"))
    while p >= 0:
        t = u32(d, p + 4)
        if vma <= t < vma + size:
            o = lma + (t - vma)
            if (u32(d, o) == 0xE1A0C00E and u32(d, o + 4) >> 24 == 0xEB and u32(d, o + 8) == 0xE1A00001
                    and u32(d, o + 12) == 0xE12FFF1C):
                out.add(p)
        p = d.find(bytes.fromhex("004b1847"), p + 2)
    return out


def bl_target(d, h):
    hi, lo = u16(d, h), u16(d, h + 2)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    off = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    return h + 4 + (off - 0x800000 if off & 0x400000 else off)


def cursor_tables(d, end, mods):
    """{T: N}: `movs r1,#N` and within 4 instructions `bl MOD`, then within 8 instructions `ldrb rX,[rT,r0]` where
    rT was loaded from a literal in the 5 instructions before (directly or through a stack slot)."""
    out = {}
    for h in range(0, end - 4, 2):
        ins = u16(d, h)
        if ins & 0xFF00 != 0x2100:                                          # movs r1, #N
            continue
        call = next((h + 2 * k for k in range(1, 5) if bl_target(d, h + 2 * k) in mods), None)
        if call is None:
            continue
        n = ins & 0xFF
        T = None
        for k in range(1, 6):                                               # literal stored to [sp,#j] before
            x = lit(d, h - 2 * k)
            if x and ROM <= x[1] < ROM + len(d):
                T = x[1] - ROM
                break
        if T is None:
            continue
        for k in range(2, 10):
            z = u16(d, call + 2 * k)
            if z & 0xFE00 == 0x5C00 and (z >> 6) & 7 == 0:                  # ldrb rX, [rT, r0]
                out[T] = n
                break
    return out


def proofs(path):
    """{word offset: reason} for the pointer-like words inside the three tables (data)."""
    d = open(path, "rb").read()
    gp = profiles.profile_gs1(path)
    end = gp["code_end"]
    labels = code_labels(d, end)
    size = len(d)
    isptr = lambda w: ROM <= w < ROM + size
    out = {}

    def claim(T, n, why):
        nxt = next_label(labels, T)
        if nxt is not None and T + n > nxt:
            return False
        for a in range(T & ~3, T + n - 3):
            if a % 4 == 0 and isptr(u32(d, a)) and a + 4 <= T + n:
                out.setdefault(a, why)
        return True

    for T, h in menu_font(d, end).items():
        cols = [sum(isptr(u32(d, T + 32 * i + c)) for i in range(224)) for c in range(0, 32, 4)]
        if max(cols) * 8 < 224:                                         # no column is a pointer field
            claim(T, 224 * 32, f"menu font {T:06x}: 32-byte glyph record (ldrh, reader {ROM + h:#010x})")
    for T, h in credits_font(d, end).items():
        claim(T, 224 * 8, f"credits font {T:06x}: 8-byte 1-bit glyph (ldrb, reader {ROM + h:#010x})")
    for T, n in cursor_tables(d, end, remainder_veneers(d, profiles._iwram_image(d))).items():
        claim(T, n, f"byte table {T:06x} of {n} entries (ldrb with index mod {n})")
    return out


if __name__ == "__main__":
    for a, why in sorted(proofs(sys.argv[1]).items()):
        print(f"{a:06x}  {why}")
