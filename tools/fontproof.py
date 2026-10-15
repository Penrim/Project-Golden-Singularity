"""Code-shape proofs for small tables whose words the relocation heuristics can take for pointers. Each table is found
by the code that reads it (version-independent patterns), so its bounds come from that code:

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
  video DMA      `ldr rD,=DMAx_SAD; ldr r0,=SRC; ldr r1,=DST; ldr r2,=CNT; stmia rD!,{r0-r2}` (DE 0x0801BEAA) with SRC
                 in ROM, DST in palette RAM / VRAM / OAM, CNT enabled with an incrementing source: the hardware copies
                 (CNT & 0xFFFF) units of 2 or 4 bytes into video memory, so those bytes are colours/pixels/attributes.
  counted loop   a loop `head: ... bne head` with `cmp rC,#N` where rC = 0 before the loop and is incremented once per
                 iteration, no exit and no other entry; in its straight part (before any branch) `ldrb rX,[rP]` and
                 rP += 1 where rP holds T from a literal at loop entry (ES 0x080F9FDC): bytes T..T+N-1 are read
                 byte-wise.

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


# -------------------------------------------------------------------------- straight-line register tracking --
def is_branch(ins, nxt=0):
    """Conditional/unconditional branch, bl/blx pair, bx, pop {pc} or a write to pc: anything that leaves the
    straight line."""
    return (ins & 0xF000 == 0xD000 and ins & 0x0F00 not in (0x0E00,)) or ins & 0xF800 in (0xE000, 0xF000, 0xF800) \
        or ins & 0xFF80 in (0x4700, 0x4780) or ins & 0xFF00 == 0xBD00 or (ins & 0xFF00 in (0x4400, 0x4600)
                                                                          and ins & 0x87 == 0x87)


def branch_target(d, h):
    """Target of a Thumb b<cond> / b at h, else None."""
    ins = u16(d, h)
    if ins & 0xF000 == 0xD000 and ins & 0x0F00 < 0x0E00:
        off = ins & 0xFF
        return h + 4 + 2 * (off - 0x100 if off & 0x80 else off)
    if ins & 0xF800 == 0xE000:
        off = ins & 0x7FF
        return h + 4 + 2 * (off - 0x800 if off & 0x400 else off)
    return None


def writes(ins):
    """Registers an instruction writes (conservative: unknown formats write everything)."""
    top = ins >> 11
    if ins < 0x2000:                                   # shifts, add/sub register/imm3
        return {ins & 7}
    if top in (0x04, 0x06, 0x07):                      # movs / adds / subs #imm8
        return {(ins >> 8) & 7}
    if top == 0x05:                                    # cmp #imm8
        return set()
    if ins & 0xFC00 == 0x4000:                         # ALU: tst, cmp, cmn write nothing
        return set() if (ins >> 6) & 0xF in (8, 10, 11) else {ins & 7}
    if ins & 0xFF00 in (0x4400, 0x4600):               # add / mov high
        return {((ins >> 7) & 1) << 3 | ins & 7}
    if ins & 0xFF00 == 0x4500 or ins & 0xFF00 == 0x4700:
        return set()
    if top == 0x09:                                    # ldr pc-relative
        return {(ins >> 8) & 7}
    if ins & 0xF000 == 0x5000:                         # register offset: loads write rd
        return {ins & 7} if ins & 0x0E00 in (0x0600, 0x0800, 0x0A00, 0x0C00, 0x0E00) else set()
    if 0x6000 <= ins < 0x9000:                         # immediate offset: load if bit 11
        return {ins & 7} if ins & 0x0800 else set()
    if ins & 0xF800 == 0x9800 or ins & 0xF000 == 0xA000:
        return {(ins >> 8) & 7}
    if ins & 0xF000 == 0x9000 or ins & 0xFF00 == 0xB000 or ins & 0xFE00 == 0xB400:
        return set()                                   # str sp, add sp, push
    if ins & 0xF800 == 0xC000:                         # stmia: write-back
        return {(ins >> 8) & 7}
    if ins & 0xFF00 == 0xDF00:                         # svc: results in r0-r3
        return {0, 1, 2, 3}
    if ins & 0xF000 == 0xD000 or ins & 0xF800 == 0xE000:
        return set()                                   # b<cond> / b
    return set(range(16))


def track(d, lo, hi, state=None):
    """Values after running [lo, hi) straight: literal constants ('c', v) and copies; any other write forgets."""
    val = dict(state or {})
    for h in range(lo, hi, 2):
        ins = u16(d, h)
        x = lit(d, h)
        if x:
            val[(ins >> 8) & 7] = ("c", x[1])
            continue
        if ins & 0xF800 == 0x2000:                     # movs rd, #imm
            val[(ins >> 8) & 7] = ("c", ins & 0xFF)
            continue
        if ins & 0xFF00 == 0x4600:                     # mov rd, rm
            rd, rm = ((ins >> 7) & 1) << 3 | ins & 7, (ins >> 3) & 0xF
            if rm in val:
                val[rd] = val[rm]
            else:
                val.pop(rd, None)
            continue
        if ins & 0xFFC0 == 0x1C00:                     # adds rd, rn, #0
            rd, rn = ins & 7, (ins >> 3) & 7
            if rn in val:
                val[rd] = val[rn]
            else:
                val.pop(rd, None)
            continue
        for r in writes(ins):
            val.pop(r, None)
    return val


def straight_start(d, h, limit=32):
    """First instruction of the straight run that ends at h (no branch, call or return in between)."""
    s = h
    while s - 2 >= 0 and h - (s - 2) <= 2 * limit and not is_branch(u16(d, s - 2)) and not \
            (s - 4 >= 0 and u16(d, s - 4) & 0xF800 == 0xF000):
        s -= 2
    return s


DMA_SAD = {0x040000B0, 0x040000BC, 0x040000C8, 0x040000D4}


def video_dma(d, end):
    """{(SRC offset, bytes): stm offset} for ROM -> palette/VRAM/OAM copies set up with literals (module doc)."""
    out = {}
    for h in range(0, end, 2):
        ins = u16(d, h)
        if ins & 0xF8FF != 0xC007:                     # stmia rN!, {r0, r1, r2}
            continue
        val = track(d, straight_start(d, h, 12), h)
        rn = (ins >> 8) & 7
        get = lambda r: val.get(r, (None, None))[1]
        src, dst, cnt = get(0), get(1), get(2)
        if get(rn) not in DMA_SAD or src is None or dst is None or cnt is None:
            continue
        if not (ROM <= src < ROM + len(d) and 0x05000000 <= dst < 0x08000000):
            continue
        if not cnt >> 31 or (cnt >> 23) & 3 != 0 or not cnt & 0xFFFF:
            continue                                   # disabled, fixed/decrementing source, count 0
        out[(src - ROM, (cnt & 0xFFFF) * (4 if cnt >> 26 & 1 else 2))] = h
    return out


def counted_loops(d, end):
    """{(T, N): loop head} for counted byte loops (module doc)."""
    out = {}
    heads = {}                                         # branch target -> number of branches to it
    for h in range(0, end, 2):
        t = branch_target(d, h)
        if t is not None:
            heads[t] = heads.get(t, 0) + 1
    for B in range(2, end, 2):
        ins = u16(d, B)
        if ins & 0xFF00 != 0xD100 or not ins & 0x80:   # bne backwards
            continue
        head = branch_target(d, B)
        c = u16(d, B - 2)
        if B - head > 0x100 or c & 0xF800 != 0x2800 or not c & 0xFF or heads.get(head) != 1:
            continue
        rc, n = (c >> 8) & 7, c & 0xFF
        body = range(head, B, 2)
        skips, ok = [], True
        for x in body:
            y = u16(d, x)
            t = branch_target(d, x)
            if t is not None:
                if not head <= t <= B:
                    ok = False                         # an exit
                elif t > x:
                    skips.append((x + 2, t))
            elif is_branch(y) or (x >= 2 and u16(d, x - 2) & 0xF800 == 0xF000):
                ok = False                             # call, return or jump inside the loop
        inc_c = [x for x in body if rc in writes(u16(d, x))]
        if not ok or len(inc_c) != 1 or u16(d, inc_c[0]) != 0x3001 | rc << 8 \
                or any(a <= inc_c[0] < b for a, b in skips):
            continue
        entry = track(d, straight_start(d, head), head)
        if entry.get(rc) != ("c", 0):
            continue
        homes = {r: v[1] for r, v in entry.items() if v[0] == "c" and ROM <= v[1] < ROM + len(d)}
        first_branch = next((x for x in body if branch_target(d, x) is not None), B)
        val = dict(entry)
        reads, incs = set(), set()
        for x in range(head, first_branch, 2):
            y = u16(d, x)
            if y & 0xFFC0 == 0x7800:                   # ldrb rX, [rP, #0]
                rp = (y >> 3) & 7
                for r, T in homes.items():
                    if val.get(rp) == ("c", T) and r not in incs:
                        reads.add(r)
            if y & 0xF8FF == 0x3001 and (y >> 8) & 7 in homes:                       # adds rP, #1
                incs.add((y >> 8) & 7)
            elif y & 0xFF00 == 0x4400:                                              # add rd(hi), rm
                rd, rm = ((y >> 7) & 1) << 3 | y & 7, (y >> 3) & 0xF
                if rd in homes and val.get(rm) == ("c", 1):
                    incs.add(rd)
            val = track(d, x, x + 2, val) if not (y & 0xF8FF == 0x3001 or y & 0xFF00 == 0x4400) else \
                {k: v for k, v in val.items() if k not in writes(y)}
        for r in reads & incs:
            if sum(r in writes(u16(d, x)) for x in body) == 1:                     # only the increment
                out[(homes[r] - ROM, n)] = head
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

    def claim(T, n, why, bounded=True):
        """bounded: the size is an upper bound from an index range, so the table must end before the next label;
        otherwise the code reads exactly these bytes (labels inside are other names for the same block)."""
        nxt = next_label(labels, T)
        if bounded and nxt is not None and T + n > nxt:
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
    for (T, n), h in video_dma(d, end).items():
        claim(T, n, f"video DMA source {T:06x}+{n:#x} (DMA set up at {ROM + h:#010x})", bounded=False)
    for (T, n), h in counted_loops(d, end).items():
        claim(T, n, f"byte table {T:06x} read by a {n}-step ldrb loop at {ROM + h:#010x}", bounded=False)
    return out


if __name__ == "__main__":
    for a, why in sorted(proofs(sys.argv[1]).items()):
        print(f"{a:06x}  {why}")
