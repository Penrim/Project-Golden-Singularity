"""Find every absolute ROM pointer in a GBA ROM so the whole game can be moved to another ROM address.

Sources of pointers:
  - literal pools referenced by Thumb `ldr rX,[pc,#imm]` and ARM `ldr rX,[pc,#+-imm]` in the code region
  - the Master File Table
  - pointer tables: runs of consecutive pointer-like words
Compressed files (e.g. map code) are handled separately by the builder.
"""
import struct

ROM = 0x08000000
STUB = bytes.fromhex("004c2047")  # ldr r4,[pc,#0]; bx r4 (engine jump-table entry)


def is_ptr(w, size):
    return ROM <= w < ROM + size


def literal_targets(d, start, end):
    """Offsets of words loaded PC-relative by Thumb or ARM code in [start, end)."""
    lits = set()
    for h in range(start, end - 1, 2):
        ins = d[h] | (d[h + 1] << 8)
        if ins & 0xF800 == 0x4800:  # Thumb LDR Rd, [PC, #imm8*4]
            lits.add(((h + 4) & ~3) + (ins & 0xFF) * 4)
    for a in range(start & ~3, end - 3, 4):
        w = struct.unpack_from("<I", d, a)[0]
        if w & 0x0F7F0000 == 0x051F0000 and w >> 28 != 0xF:  # ARM LDR Rd, [PC, #+-imm12]
            imm = w & 0xFFF
            lits.add(a + 8 + (imm if w & 0x00800000 else -imm))
    return {x for x in lits if start <= x < end}


def pointer_runs(d, start, end, size, min_run):
    out = set()
    run = []
    for a in range(start & ~3, end - 3, 4):
        if is_ptr(struct.unpack_from("<I", d, a)[0], size):
            run.append(a)
        else:
            if len(run) >= min_run:
                out.update(run)
            run = []
    if len(run) >= min_run:
        out.update(run)
    return out


def strided_runs(d, start, end, size, min_run=3, strides=tuple(range(8, 0x104, 4))):
    """Pointer-like words repeating at a constant stride (arrays of structs with a pointer field)."""
    ptrs = [a for a in range(start & ~3, end - 3, 4) if is_ptr(struct.unpack_from("<I", d, a)[0], size)]
    pset = set(ptrs)
    out = set()
    for a in ptrs:
        for st in strides:
            if a - st in pset:
                continue  # not the start of a run for this stride
            n, x = 0, a
            while x in pset:
                n += 1; x += st
            if n >= min_run:
                out.update(range(a, x, st))
    return out


def bl_targets(d, start, end):
    """Thumb BL targets (function entries) found by scanning the code region."""
    out = set()
    for h in range(start, end - 3, 2):
        hi = d[h] | (d[h + 1] << 8)
        lo = d[h + 2] | (d[h + 3] << 8)
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            off = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
            if off & 0x400000:
                off -= 0x800000
            t = h + 4 + off
            if start <= t < end:
                out.add(t)
    return out


def code_coverage(d, entries, end):
    """Recursive-descent Thumb disassembly. Returns the set of halfword offsets that are instructions."""
    code = set()
    work = [e for e in entries if 0 <= e < end]
    while work:
        pc = work.pop()
        while 0 <= pc < end - 1 and pc not in code:
            ins = d[pc] | (d[pc + 1] << 8)
            code.add(pc)
            if ins & 0xF800 == 0xF000 and pc + 3 < end:            # BL (two halfwords)
                lo = d[pc + 2] | (d[pc + 3] << 8)
                if lo & 0xF800 == 0xF800:
                    off = ((ins & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
                    if off & 0x400000:
                        off -= 0x800000
                    work.append(pc + 4 + off)
                    code.add(pc + 2)
                    pc += 4
                    continue
                break
            if ins & 0xF800 == 0xE000:                              # B
                off = (ins & 0x7FF) << 1
                if off & 0x800:
                    off -= 0x1000
                work.append(pc + 4 + off)
                break
            if ins & 0xF000 == 0xD000 and ins & 0x0F00 not in (0x0E00, 0x0F00):  # Bcond
                off = (ins & 0xFF) << 1
                if off & 0x100:
                    off -= 0x200
                work.append(pc + 4 + off)
            elif ins & 0xFF00 == 0xBD00 or ins & 0xFF80 == 0x4700:  # POP {..pc} / BX
                break
            elif ins & 0xFF87 == 0x4687:                           # MOV pc, Rm
                break
            elif ins & 0xFF00 == 0xDF00 and False:
                pass
            pc += 2
    return code


def strong_code_coverage(d, roots, end, size):
    """Code coverage grown only from trusted roots: follow BL/B from covered code and add odd literal-pool
    pointers loaded by covered code as new roots, until nothing changes."""
    code = set()
    roots = {r for r in roots if 0 <= r < end}
    done = set()
    while roots - done:
        new = roots - done
        done |= new
        code |= code_coverage(d, new, end)
        for h in list(code):
            ins = d[h] | (d[h + 1] << 8)
            if ins & 0xF800 == 0x4800:
                la = ((h + 4) & ~3) + (ins & 0xFF) * 4
                if la + 4 <= len(d):
                    w = struct.unpack_from("<I", d, la)[0]
                    if w & 1 and ROM <= w < ROM + end:
                        roots.add((w & ~1) - ROM)
    return code


def stub_targets(rom, end):
    """Targets of engine jump-table stubs (ldr r4,[pc]; bx r4; .word fn) at the start of MFT code files."""
    d = rom.data
    out = set()
    for e in rom.entries:
        if not (0 <= e < end):
            continue
        o = e
        while d[o:o + 4] == STUB:
            w = struct.unpack_from("<I", d, o + 4)[0]
            if w & 1 and ROM <= w < ROM + end:
                out.add((w & ~1) - ROM)
            o += 8
    return out


def is_prologue(d, off):
    """Thumb function prologue: push {..., lr} (optionally after a mov/sub)."""
    if not (0 <= off < len(d) - 1):
        return False
    h = d[off] | (d[off + 1] << 8)
    return h & 0xFF00 == 0xB500


def analyse(rom, code_end, protected=(), explicit=(), extra_roots=()):
    """Return (relocs, stats). relocs = sorted word offsets whose value is a ROM pointer to relocate.

    protected: (start, end) ranges of known data blobs (e.g. text) where no heuristic applies;
    explicit: pointer offsets known from format parsers (always relocated)."""
    d, size = rom.data, len(rom.data)
    lits = {a for a in literal_targets(d, 0, code_end) if a % 4 == 0 and is_ptr(struct.unpack_from("<I", d, a)[0], size)}
    mft = {rom.mft_off + 4 * i for i in range(len(rom.entries))}
    runs_code = pointer_runs(d, 0, code_end, size, 2)
    runs_data = set()  # data region: heuristics produced false positives in text/byte tables; MFT + m4a only
    strided = strided_runs(d, 0, code_end, size)
    relocs = lits | mft | runs_code | runs_data | strided
    # Singletons: values equal to an address the game demonstrably uses, or odd pointers to a function prologue.
    known = {struct.unpack_from("<I", d, a)[0] for a in relocs}
    bls = bl_targets(d, 0, code_end)
    known |= {ROM + t + 1 for t in bls}
    # trusted roots: jump-table stubs, caller-supplied roots, and function pointers found in confirmed pointer
    # tables/literal pools that point at a push {..., lr} prologue
    roots = stub_targets(rom, code_end) | set(extra_roots)
    for a in lits | runs_code | strided:
        w = struct.unpack_from("<I", d, a)[0]
        if w & 1 and (w & ~1) - ROM < code_end and is_prologue(d, (w & ~1) - ROM):
            roots.add((w & ~1) - ROM)
    code = strong_code_coverage(d, roots, code_end, size)
    singles = set()
    for a in range(0, code_end - 3, 4):
        if a in relocs:
            continue
        w = struct.unpack_from("<I", d, a)[0]
        if not is_ptr(w, size):
            continue
        near = (a < code_end and abs((w & ~1) - ROM - a) < 0x10000  # data next to itself, in the code region
                and a not in code and a + 2 not in code)
        if w in known or near or (w & 1 and (w & ~1) - ROM < code_end and is_prologue(d, (w & ~1) - ROM)):
            singles.add(a)
    relocs |= singles
    dropped = {a for a in relocs if any(lo <= a < hi for lo, hi in protected)}
    relocs = (relocs - dropped) | set(explicit)
    allptr = {a for a in range(0, size - 3, 4) if is_ptr(struct.unpack_from("<I", d, a)[0], size)}
    stats = {
        "pointer_like_words": len(allptr),
        "literal_pool": len(lits),
        "mft": len(mft),
        "runs_code": len(runs_code - lits),
        "runs_data": len(runs_data - mft),
        "strided": len(strided - runs_code - runs_data - lits),
        "singles": len(singles),
        "protected_dropped": len(dropped - set(explicit)),
        "code_bytes": 2 * len(code),
        "relocated": len(relocs),
        "unclassified_code": len({a for a in allptr if a < code_end} - relocs),
        "unclassified_data": len({a for a in allptr if a >= code_end} - relocs),
    }
    return sorted(relocs), stats
