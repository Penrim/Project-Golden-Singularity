"""Step 5 (data part): evidence for the byte-like guesses, the data noise, the SUSPECT words and the hand-made
exclusion lists (data/reloc_exclude_<code>.txt), so that each word gets a category with its evidence.

Evidence sources (a word is proven only by one of them; contradictions are reported):
  sprite   format parser of the sprite table. Lookup function `T + 20 * (id & 0xFFF)` (USA 0x08185008, reached
           through the engine stub at 0x08185000). Records {u8 w, u8 h, u16, u8, u8 anims, u8, u8, u16, u8 fmt, u8,
           u32 frames, u32 anims}; the callers read +0/+1/+4/+5/+6/+7/+0xA with ldrb, +2 with ldrh, +0xC/+0x10 with
           ldr (USA 0x0800B7F6..0x0800B840, 0x0800BA0C, 0x0800BE2A). The table ends where the first anim script
           starts (USA 512 records, 0x185024-0x187824). anims -> `anims` script pointers (index < anims is checked
           at USA 0x0800BA0E/0x0800BE2E); scripts are byte pairs {op, arg} read with ldrb by the interpreter (USA
           0x0800AA94); commands 0xEF..0xFF through its jump table (0x0800AAC8): 0xEF delete, 0xF1 hold (pos -= 2),
           0xFD jump to byte position arg, 0xFE switch animation -- these end the sequential walk.
           frames -> table of frame pointers; frame data is decoded by record fmt (USA 0x0800AE8E): 1 = GS format 0/1
           (ARM 0x08002544 = gsfs), 3 = two-stream LZ (IWRAM 0x030005C0 / Thumb 0x0800A97C; first u16 = offset of
           the control stream, 0 = a raw stream follows), 0 = raw stream (ARM 0x08009BB8 mode 0: bytes <= 0xDF are
           pixels, > 0xDF skip, 0 ends). A frame is proven when its decoder stops at the next frame/table (format 0
           may prefetch 2 bytes).
  code     typeflow.Flow extended (AccessFlow): code coverage plus the instructions after `mov ip, pc; bx rN`
           (IWRAM routines return with add ip, ip, #1; bx ip) and switch-table cases (ldr rN,[table + 4i]; mov pc,
           rN with its cmp bound); every load is logged with width and source; byte tables read with an unknown index
           (stride 1) and leaf index functions (`T + s * (id & mask)`) give table sources. A narrow read (ldrb/ldrh)
           of any byte of a word = data. Field reads spread over the table up to the next label (as typeflow) and
           the index mask.
  stub     engine stub (ldr r4,[pc,#0]; bx r4; .word fn) that map code or confirmed code jumps to.
  file     inside a proven packed part of an MFT file (filemap.file_spans).
  probe    recorded all-words probe (build/probe_all/<lang>.txt): narrow-only = data, wide + used = pointer.

  python dataproof.py GS1.gba probe.txt [--list [--all]] [--json OUT.json]
"""
import bisect, collections, math, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom, decompress_span
import build_gs1_reloc, filemap, gfxlz, m4a, profiles, reloc, typeflow, wordmap

ROM = 0x08000000
# sprite lookup: ldr r2,=0xFFF; adds r3,r0,#0; ands r3,r2; lsls r0,r3,#2; adds r0,r0,r3; ldr r3,=T; lsls r0,r0,#2;
# adds r0,r0,r3; bx lr
SPRITE_FN = bytes.fromhex("044a031c13409800c018034b8000c0187047")
SCRIPT_END = {0xEF, 0xF1, 0xFD, 0xFE}       # delete, hold, jump (loop), switch animation: the walk stops
REC = 20
XS = list(range(0x2000)) + list(range(0x2000, 0x10000, 0x101))   # ids tried on index functions
TARGETS = ("guess-WEAK-bytelike", "data-noise", "SUSPECT")
FORMAT_CATS = ("mft", "music", "text-ptr", "literal", "typed-pointer", "sample-data", "music-data", "text-data",
               "probe-pointer")
GRADES = ("exact", "parser", "mask", "label", "byte-index")
KNOWN_PTR = ("mft", "music", "text-ptr", "literal", "typed-pointer")    # wordmap categories proven elsewhere


def u32(d, a):
    return struct.unpack_from("<I", d, a)[0]


# ------------------------------------------------------------------------------------------------ halfword LZ --
HW_LZ = bytes.fromhex("0231a0e3000000eab220c1e08330b0e1b220d0e0fbffff3a")


def hw_lz_span(d, s):
    """End of a halfword LZ stream (ARM routine USA 0x08002298, run from the stack by 0x080052F4): a flag halfword
    (MSB first, sentinel bit), 0 = literal halfword, 1 = back-reference halfword (distance r >> 5, length
    (r & 31) + 2 halfwords), 0 ends."""
    pos, r3 = s, 0x80000000

    def lsl1():
        nonlocal r3
        c = r3 >> 31
        r3 = (r3 << 1) & 0xFFFFFFFF
        return c
    c = lsl1()
    while True:
        r2 = d[pos] | d[pos + 1] << 8
        pos += 2
        if c == 0:
            c = lsl1()
        elif r3:
            if r2 == 0:
                return pos
            c = lsl1()
        else:
            v = (2 * r2 + 1) << 16
            c, r3 = (v >> 32) & 1, v & 0xFFFFFFFF


# ---------------------------------------------------------------------------------------------- sprite frames --
def gs0_span(d, s):
    """End of a GS format 0 stream (as gsfs._decompress_c0, but with the ARM routine's minimum offset width of 1
    bit at the start of the output; gsfs would fail there)."""
    pos = s + 1
    n, bitnum = 0, 0
    bits = d[pos] | d[pos + 1] << 8
    pos += 2
    while True:
        count = 0
        if bits & 1:
            n += 1; bits >>= 9; bitnum -= 9
        elif bits & 3 == 0:
            count = 2; bits >>= 2; bitnum -= 2
        elif bits & 7 == 2:
            count = 3; bits >>= 3; bitnum -= 3
        elif bits & 0xF == 6:
            count = 4; bits >>= 4; bitnum -= 4
        elif bits & 0x1F == 0xE:
            count = 5; bits >>= 5; bitnum -= 5
        elif bits & 0x7F == 0x1E:
            count = 6; bits >>= 7; bitnum -= 7
        elif bits & 0x7F == 0x5E:
            count = 7; bits >>= 7; bitnum -= 7
        elif bits & 0x3F == 0x3E:
            count = 7 + ((bits >> 6) & 3); bits >>= 8; bitnum -= 8
            if count == 7:
                count = 10 + (bits & 0x7F); bits >>= 7; bitnum -= 7
                if count == 10:
                    return pos
        if bitnum < 0:
            bitnum += 16; bits += (d[pos] << bitnum) + (d[pos + 1] << (8 + bitnum)); pos += 2
        if count:
            if bits & 1 == 0:
                bits >>= 1; bitnum -= 1
                limit = (n - 33) & 0xFFFFFFFF
                width = 12 if limit >= 0x800 else max(1, limit.bit_length())
                bits >>= width; bitnum -= width
            else:
                bits >>= 6; bitnum -= 6
            if bitnum < 0:
                bitnum += 16; bits += (d[pos] << bitnum) + (d[pos + 1] << (8 + bitnum)); pos += 2
            n += count


def raw_span(d, s):
    """Raw sprite stream (ARM 0x08009BB8, mode 0): ends after the first 0 byte."""
    return d.index(0, s) + 1


def lz3_span(d, s):
    """Two-stream LZ (IWRAM 0x030005C0): u16 L; literals from s+2, control bytes (LSB first, 0 = back-reference of
    a big-endian u16, 0 ends; length nibble 0 -> one more byte) from s+L. L = 0: a raw stream follows at s+2."""
    L = d[s] | d[s + 1] << 8
    if L == 0:
        return raw_span(d, s + 2)
    lit, ctl = s + 2, s + L
    r3 = d[ctl] | 0x100
    ctl += 1
    while True:
        c = r3 & 1
        r3 >>= 1
        if c == 0:
            r4 = d[ctl] << 8 | d[ctl + 1]
            ctl += 2
            if r4 == 0:
                if lit > s + L:
                    raise ValueError("literal stream runs into the control stream")
                return ctl
            if r4 >> 12 == 0:
                ctl += 1
        elif r3 == 0:
            r3 = d[ctl] | 0x100
            ctl += 1
        else:
            lit += 1


def frame_span(d, s, fmt):
    if fmt == 1:
        if d[s] == 0:
            return gs0_span(d, s)
        if d[s] == 1:
            return decompress_span(d, s)[1]
        raise ValueError("format byte")
    if fmt == 3:
        return lz3_span(d, s)
    if fmt == 0:
        return raw_span(d, s)
    raise ValueError(f"sprite format {fmt}")


# ------------------------------------------------------------------------------------------------ m4a tracks --
def track_bytes(d, song_table):
    """{byte: track start} for the bytes of every m4a track stream (the sound engine reads them with ldrb), from the
    start to its FINE (0xB1) or GOTO (0xB2 + pointer), as m4a.track_pointers walks them; the 4 bytes of each
    GOTO/PATT/REPT pointer are left out (those are format-proven pointers)."""
    size = len(d)
    out = {}
    for _, h in m4a.song_headers(d, song_table):
        if h + 8 > size or d[h] > 16:
            continue
        for k in range(d[h]):
            t = u32(d, h + 8 + 4 * k)
            if not (ROM <= t < ROM + size):
                continue
            start = p = t - ROM
            ptrs = set()
            while p < min(start + 0x10000, size - 5):
                c = d[p]
                if c == 0xB1:
                    p += 1
                    break
                if c in (0xB2, 0xB3):
                    ptrs.update(range(p + 1, p + 5))
                    p += 5
                    if c == 0xB2:
                        break
                    continue
                if c == 0xB5:
                    ptrs.update(range(p + 2, p + 6))
                    p += 6
                    continue
                p += 4 if c == 0xB9 else 1
            for b in range(start, p):
                if b not in ptrs:
                    out.setdefault(b, start)
    return out


# ---------------------------------------------------------------------------------------------- sprite table --
def sprite_area(d, end):
    """Parse the sprite table, its anim scripts, frame tables and frames. Returns a dict:
    T, n, ptr {word: why}, data {word: why}, bytes {offset: kind}, problems [], span (lo, hi)."""
    fn = d.find(SPRITE_FN, 0, end)
    assert fn > 0 and d.find(SPRITE_FN, fn + 1, end) < 0, "sprite lookup function not unique"
    assert u32(d, fn + 0x14) == 0xFFF
    T = u32(d, fn + 0x18) - ROM
    size = len(d)
    isptr = lambda w: ROM <= w < ROM + size
    out = {"fn": fn, "T": T, "bytes": {}, "ptr": {}, "data": {}, "problems": [], "dead": {}}
    mark = lambda lo, hi, k: out["bytes"].update(dict.fromkeys(range(lo, hi), k))
    first_ref, i, recs = end, 0, []
    while T + REC * (i + 1) <= first_ref and i < 0x1000:
        r = T + REC * i
        rec = d[r:r + REC]
        if any(rec):
            fr, an = u32(d, r + 12), u32(d, r + 16)
            if not (rec[0] and rec[1] and isptr(an) and (fr == 0 or isptr(fr))):
                out["problems"].append(f"record {i} at {r:#x} malformed")
                break
            first_ref = min(first_ref, an - ROM, *([fr - ROM] if fr else []))
            recs.append((i, r))
        i += 1
    out["n"], out["end"] = i, T + REC * i
    mark(T, T + REC * i, "record")
    for k in range(i):
        r = T + REC * k
        for w in (0, 4, 8):
            out["data"][r + w] = f"sprite record {k} +{w:#x} (u8/u16 fields)"
    scripts = collections.defaultdict(list)       # script -> [(record, anim)]
    frametabs = collections.defaultdict(set)      # frame table -> {fmt}
    frames_used = collections.defaultdict(set)    # frame table -> frame numbers the scripts show
    for idx, r in recs:
        an, cnt, fr = u32(d, r + 16) - ROM, d[r + 5], u32(d, r + 12)
        out["ptr"][r + 16] = f"sprite record {idx} anim table (+0x10)"
        if fr:
            out["ptr"][r + 12] = f"sprite record {idx} frame table (+0x0C)"
            frametabs[fr - ROM].add(d[r + 10])
        for k in range(cnt):
            e = an + 4 * k
            s = u32(d, e)
            if not isptr(s):
                out["problems"].append(f"record {idx} anim {k} at {e:#x}: {s:#x}")
                continue
            out["ptr"][e] = f"sprite record {idx} anim {k} (script pointer)"
            mark(e, e + 4, "anim table")
            scripts[s - ROM].append((idx, fr))
    for s, users in scripts.items():
        pos = 0
        while pos < 256:
            op = d[s + pos]
            pos += 2
            if op <= 0xEE:
                for _, fr in users:
                    if fr:
                        frames_used[fr - ROM].add(op)
            if op in SCRIPT_END:
                if op == 0xFD and (d[s + pos - 1] % 2 or d[s + pos - 1] >= pos):
                    out["problems"].append(f"script {s:#x}: jump outside")
                break
        else:
            out["problems"].append(f"script {s:#x}: no end within 256 bytes")
        mark(s, s + pos, "script")
        for a in range((s & ~3), s + pos, 4):
            out["data"].setdefault(a, f"anim script {s:#x} (ldrb op/arg pairs)")
    # frame tables: entries while pointer-like; every entry must decode up to the next frame or table
    starts = set()
    lens = {}
    for F in frametabs:
        k = 0
        while isptr(u32(d, F + 4 * k)) and F + 4 * k not in frametabs or (k == 0 and isptr(u32(d, F))):
            starts.add(u32(d, F + 4 * k) - ROM)
            k += 1
            if F + 4 * k in frametabs:
                break
        lens[F] = k
    bounds = sorted(starts | set(frametabs))
    for F, fmts in frametabs.items():
        used = frames_used.get(F, set())
        mark(F, F + 4 * lens[F], "frame table")
        for k in range(lens[F]):
            s = u32(d, F + 4 * k) - ROM
            nxt = bounds[bisect.bisect_right(bounds, s)] if bisect.bisect_right(bounds, s) < len(bounds) else end
            spans = set()
            for f in fmts:
                try:
                    spans.add(frame_span(d, s, f))
                except (IndexError, ValueError):
                    spans.add(None)
            e = spans.pop() if len(spans) == 1 else None
            ok = e is not None and nxt - 3 <= e <= nxt + 2
            if not ok and e is not None and e > nxt + 2:
                # frames sharing a tail: the next frame starts inside this one (USA table 0x30FBB4, entries 7/8);
                # proven when the decoder stops at a later boundary instead (data up to the next frame start)
                later = bounds[bisect.bisect_right(bounds, nxt):][:4] + [end]
                ok = any(b - 3 <= e <= b + 2 for b in later)
            if not ok:
                out["problems"].append(f"frame table {F:#x} entry {k}: frame {s:#x} fmt {sorted(fmts)} ends "
                                       f"{e if e is None else hex(e)}, next {nxt:#x}")
                continue
            why = f"frame {k} of table {F:#x}" + ("" if k in used else " (not shown by any script)")
            out["ptr"][F + 4 * k] = why
            mark(s, min(e, nxt), "frame")
            for a in range(s & ~3, min(e, nxt), 4):
                if a + 4 <= min(e, nxt) or a not in out["ptr"]:
                    out["data"].setdefault(a, f"packed sprite frame {s:#x} (fmt {sorted(fmts)[0]})")
    # words whose bytes are partly frame and partly the next frame (unaligned frames): data as well
    for a in list(out["data"]):
        if a in out["ptr"]:
            if out["bytes"].get(a) in ("frame table", "anim table"):
                del out["data"][a]
            else:
                out["problems"].append(f"word {a:#x}: pointer ({out['ptr'][a]}) and data ({out['data'][a]})")
    lo = T
    hi = max(out["bytes"]) + 1
    out["span"] = (lo, hi)
    # pointer-like words in the area that no rule explains (tails of anim tables beyond the count, padding)
    for a in range(lo & ~3, hi, 4):
        if a not in out["ptr"] and a not in out["data"] and isptr(u32(d, a)):
            out["dead"][a] = "inside the sprite area, not reached by any record (beyond anim count / padding)"
    return out


# ------------------------------------------------------------------------------------------- extended code --
def switch_targets(d, code, end):
    """Case entries of Thumb switch tables in confirmed code: `ldr rT,=TABLE ... ldr rN,[rI,rT] ; mov pc,rN` with a
    `cmp rI,#N ; bhi/bls` bound in the 8 instructions before. Returns {table entry offset: target}."""
    out = {}
    for h in code:
        ins = d[h] | d[h + 1] << 8
        if ins & 0xFF87 != 0x4687:                    # mov pc, rN
            continue
        rn = (ins >> 3) & 0xF
        table = bound = None
        for k in range(1, 12):
            p = h - 2 * k
            if p not in code:
                break
            x = d[p] | d[p + 1] << 8
            if x & 0xF800 == 0x4800 and table is None:   # ldr rT, [pc, #imm]
                la = ((p + 4) & ~3) + (x & 0xFF) * 4
                v = u32(d, la)
                if ROM <= v < ROM + end:
                    table = v - ROM
            if x & 0xF800 == 0x2800 and bound is None:   # cmp rI, #N
                nxt = d[p + 2] | d[p + 3] << 8
                if nxt & 0xFF00 in (0xD800, 0xD900):     # bhi / bls
                    bound = x & 0xFF
        if table is None or bound is None:
            continue
        for i in range(bound + 1):
            v = u32(d, table + 4 * i)
            if ROM <= v < ROM + end:
                out[table + 4 * i] = (v & ~1) - ROM
    return out


def extended_code(d, code, end, tables=frozenset()):
    """Confirmed code + continuations after `mov ip, pc; bx rN` + switch cases, until nothing changes."""
    code = set(code)
    done = set()
    while True:
        roots = set()
        for h in code:
            if d[h] | d[h + 1] << 8 == 0x46FC and (d[h + 2] | d[h + 3] << 8) & 0xFF87 == 0x4700:
                roots.add(h + 4)
        roots |= set(switch_targets(d, code, end).values())
        roots -= done
        roots = {r for r in roots if r not in code}
        if not roots:
            return code
        done |= roots
        new = reloc.code_coverage(d, roots, end)
        code |= {h for h in new if h & ~3 not in tables}


# --------------------------------------------------------------------------------------------- access flow --
class AccessFlow(typeflow.Flow):
    """typeflow.Flow that logs every load (source, width) and knows byte tables read with an unknown index and
    leaf index functions T + s * (id & mask)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.acc = collections.defaultdict(set)       # source -> {(width, insn)}
        self.idxfun = self._index_functions()
        import fileflow
        self.unpack = fileflow._copy_routines(self)     # wrapper -> "unpack-gs" / "unpack-lz" (decoder copied to RAM)
        self.unpack.update(self._hw_wrappers())
        self.blobs = {}                                 # ROM offset passed to a decoder -> (kind, insn)
        self.bound = {}                               # table offset -> entries (index mask)
        for T, s, n in self.idxfun.values():
            self.bound[T] = n

    def _hw_wrappers(self):
        """Functions that DMA-copy the halfword LZ routine (ARM, USA 0x08002298, 0x54 bytes) to the stack and run it
        with (src, dst): kind "unpack-hw"."""
        r = self.d.find(HW_LZ, 0, self.end)
        out = {}
        if r < 0:
            return out
        for o, ins in self.insns.items():
            if ins.mnemonic != "push" or "lr" not in ins.op_str:
                continue
            body = [self.insns.get(o + 2 * k) for k in range(24)]
            lits = {self.u32(((i.address + 4) & ~3) + i.operands[1].mem.disp - ROM) for i in body
                    if i is not None and i.mnemonic == "ldr" and "pc" in i.op_str}
            if 0x040000D4 in lits and ROM + r in lits:
                out[o] = "unpack-hw"
        return out

    def _index_functions(self):
        """Small functions without memory loads (literals aside) or calls that return r0 = T + s * k for a bounded
        k: masks (id & 0xFFF), clamps (cmp; bls; movs r0, #0) and offsets (id - 8) are run concretely for every id
        0..0x1FFF and sampled above (XS). Returns {entry: (T, s, entries)}."""
        out = {}
        for e in self.entries:
            prog, o = {}, e
            while o in self.insns and len(prog) < 24:
                ins = self.insns[o]
                prog[o] = ins
                if ins.mnemonic == "bx":
                    break
                o += 2
            last = self.insns.get(o)
            if last is None or last.mnemonic != "bx" or any(
                    i.mnemonic in ("bl", "str", "strh", "strb", "ldrh", "ldrb", "ldrsh", "ldrsb", "stm", "ldm", "svc")
                    or (i.mnemonic == "ldr" and "pc" not in i.op_str) for i in prog.values()):
                continue
            try:
                probe = {self._run(prog, e, x) for x in (0, 1, 2, 3, 100)}
            except (KeyError, ValueError, IndexError):
                continue
            if not all(v is not None and self.is_rom(v) for v in probe) or len(probe) < 3:
                continue
            try:
                vals = {self._run(prog, e, x) for x in XS}
            except (KeyError, ValueError, IndexError):
                continue
            T = min(vals)
            diffs = sorted(v - T for v in vals if v != T)
            st = 0
            for dv in diffs:
                st = math.gcd(st, dv)
            if not st or st > 0x1000 or not all(self.is_rom(v) for v in vals):
                continue
            n = (max(vals) - T) // st + 1
            if len(vals) == n:                   # every entry 0..n-1 reachable: a contiguous table
                out[e] = (T - ROM, st, n if n < 0x10000 else None)
        return out

    def _run(self, prog, e, x):
        """Run a small Thumb function concretely with r0 = x; returns r0."""
        r = {"r0": x}
        fl = {"n": 0, "z": 0, "c": 0, "v": 0}
        pc, steps = e, 0
        name = lambda op: self.md.reg_name(op.reg)
        while steps < 64:
            steps += 1
            ins = prog[pc]
            m, ops = ins.mnemonic, ins.operands
            nxt = pc + 2
            if m in ("push", "pop"):
                pass
            elif m == "bx":
                return r["r0"]
            elif m == "ldr":
                r[name(ops[0])] = self.u32(((ins.address + 4) & ~3) + ops[1].mem.disp - self.base)
            elif m == "cmp":
                a = r[name(ops[0])]
                b = ops[1].imm if ops[1].type == typeflow.ARM_OP_IMM else r[name(ops[1])]
                res = (a - b) & 0xFFFFFFFF
                fl = {"n": res >> 31, "z": int(res == 0), "c": int(a >= b),
                      "v": int(((a ^ b) & (a ^ res)) >> 31 & 1)}
            elif m.startswith("b") and len(m) <= 3 and ops and ops[0].type == typeflow.ARM_OP_IMM:
                cond = m[1:]
                take = {"": True, "eq": fl["z"], "ne": not fl["z"], "hs": fl["c"], "lo": not fl["c"],
                        "hi": fl["c"] and not fl["z"], "ls": not fl["c"] or fl["z"], "mi": fl["n"], "pl": not fl["n"],
                        "ge": fl["n"] == fl["v"], "lt": fl["n"] != fl["v"], "gt": not fl["z"] and fl["n"] == fl["v"],
                        "le": fl["z"] or fl["n"] != fl["v"]}[cond]
                if take:
                    nxt = ops[0].imm - self.base
            elif m in ("movs", "mov", "adds", "add", "subs", "sub", "lsls", "lsrs", "ands", "orrs", "muls"):
                dst = name(ops[0])
                val = lambda op: op.imm if op.type == typeflow.ARM_OP_IMM else r[name(op)]
                a = val(ops[1]) if len(ops) == 3 or m in ("movs", "mov") else r[dst]
                b = val(ops[-1])
                v = {"movs": b, "mov": b, "adds": a + b, "add": a + b, "subs": a - b, "sub": a - b,
                     "lsls": a << b, "lsrs": a >> b, "ands": a & b, "orrs": a | b, "muls": a * b}[m]
                r[dst] = v & 0xFFFFFFFF
            else:
                raise ValueError(m)
            pc = nxt
        raise ValueError("loop")

    # index plus a constant: ("lino", identity, factor, offset) (typeflow drops it: (i << 3) + 4 -> unknown)
    def _add(self, a, b):
        for x, y in ((a, b), (b, a)):
            if x and y and y[0] == "c" and y[1] is not None:
                small = y[1] if y[1] < 0x80000000 else y[1] - 0x100000000
                if abs(small) < 0x10000 and small:
                    if x[0] == "lin":
                        return ("lino", x[1], x[2], small)
                    if x[0] == "lino":
                        return ("lino", x[1], x[2], x[3] + small)
                    if x[0] == "idxo":
                        return ("idxo", x[1], x[2], x[3] + small)
                if x[0] == "lino" and self.is_rom(y[1]):
                    return ("idxo", y[1], x[2], x[3])        # table base keeps its label; the offset goes to the field
        return super()._add(a, b)

    def _scale(self, a, k):
        if a and a[0] == "lino" and k:
            return ("lino", a[1], a[2] * k, a[3] * k)
        return super()._scale(a, k)

    def _source(self, base, idx, disp, has_idx):
        s = super()._source(base, idx, disp, has_idx)
        if s is None and base and base[0] == "idxo" and not has_idx and base[2] > 0:
            s = ("fld", base[1] - ROM, base[2], disp + base[3])
        if s is None and has_idx:
            for b, i in ((base, idx), (idx, base)):
                if b and b[0] == "c" and self.is_rom(b[1]) and i:
                    if i[0] == "lino" and i[2] > 0:
                        s = ("fld", b[1] - ROM, i[2], disp + i[3])
                    elif i[0] == "var":
                        s = ("fld1", b[1] - ROM, 1, disp)          # byte table, unknown index
        self._last = s
        return s

    def _step(self, ins, regs, func, record=True):
        self._last = None
        m = ins.mnemonic
        r0 = regs.get("r0")                            # a call drops r0..r3
        super()._step(ins, regs, func, record)
        if record and self._last and m in ("ldr", "ldrh", "ldrb", "ldrsh", "ldrsb"):
            self.acc[self._last].add((4 if m == "ldr" else 2 if m in ("ldrh", "ldrsh") else 1, ins.address))
        if m == "bl" and ins.operands and ins.operands[0].type == typeflow.ARM_OP_IMM:
            t = self.resolve(ins.operands[0].imm - self.base)
            if t in self.unpack and record and r0 and r0[0] == "c" and self.is_rom(r0[1]):
                self.blobs.setdefault(r0[1] - ROM, (self.unpack[t], ins.address))
            if t in self.idxfun:
                T, s, n = self.idxfun[t]
                regs["r0"] = ("idx", ROM + T, s)

    def labels(self):
        """typeflow labels without fill patterns: the constant 0x08080808 (passed to a fill routine, German ROM
        0x080D57D0) would otherwise end the item table at 0x080808 inside entry 112."""
        if not hasattr(self, "_labels2"):
            pat = {(b * 0x01010101) - ROM for b in range(8, 9)}
            self._labels2 = [x for x in super().labels() if x not in pat]
        return self._labels2

    def table_end(self, T, s):
        lab = self.labels()
        k = bisect.bisect_right(lab, T)
        lim = lab[k] if k < len(lab) else self.rom_end
        if T in self.bound and self.bound[T]:
            lim = min(lim, T + s * self.bound[T])
        return min(lim, T + s * 4096)

    def narrow_bytes(self, extra_end=None, stop=None):
        """{byte offset: (source, insn, grade)} for every byte some code reads with ldrb/ldrh. grade: exact (the
        address is known), parser / mask (field spread over a table whose size the sprite parser or the index
        function's mask gives), label (field spread up to the next label, as typeflow), byte-index (a byte table
        read with an unknown index, up to the next label). stop(a): a byte that belongs to something else proven
        (music, samples, text, literals, sprite area ...): a label-bounded table ends before it."""
        out = {}
        for src, uses in self.acc.items():
            nar = sorted(u for u in uses if u[0] < 4)
            if not nar:
                continue
            insn = nar[0][1]
            w = max(u[0] for u in nar)
            if src[0] == "at":
                for k in range(w):
                    out.setdefault(src[1] + k, (src, insn, "exact"))
                continue
            _, T, s, off = src
            end, grade = (extra_end or {}).get(T), "parser"
            if end is None:
                end = self.table_end(T, s)
                lab = self.labels()
                k = bisect.bisect_right(lab, T)
                grade = "mask" if self.bound.get(T) and T + s * self.bound[T] <= (lab[k] if k < len(lab) else
                                                                                   self.rom_end) else "label"
                if src[0] == "fld1":
                    grade = "byte-index"
            i = i0 = -(off // s) if off < 0 else 0     # index offset (c - 0x20) * 32: entries start at the label
            while T + i * s < end and T + i * s + off < self.rom_size:
                a = T + i * s + off
                if a in self.rom_code or (i > i0 and grade != "parser" and stop
                                          and any(stop(a + k) for k in range(w))):
                    break
                for k in range(w):
                    out.setdefault(a + k, (src, insn, grade))
                i += 1
        return out


# -------------------------------------------------------------------------------------------- engine stubs --
def stub_users(g, gp, code):
    """Engine stub addresses that something jumps to: BL targets of confirmed code and the targets of map code
    jump-table entries (ldr r4,[pc,#0]; bx r4; .word fn)."""
    d = g.data
    out = {}
    for t in reloc.bl_targets(d, 0, gp["code_end"]):
        pass
    for h in code:
        hi, lo = d[h] | d[h + 1] << 8, d[h + 2] | d[h + 3] << 8
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            off = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
            out.setdefault(h + 4 + (off - 0x800000 if off & 0x400000 else off), f"BL at {h:#x}")
    for i in range(*gp["mapcode"]):
        b = g.decompressed(i)
        for a in range(4, len(b) - 3, 4):
            if b[a - 4:a] == reloc.STUB:
                w = u32(b, a)
                if w & 1 and ROM <= w < ROM + len(d):
                    out.setdefault((w & ~1) - ROM, f"map code {i} stub")
    return out


# ------------------------------------------------------------------------------------------------- verdicts --
def analyse(gs1_path, probe_path=None, all_words=False):
    """Per pointer-like word in the target categories (and the exclusion list): category, relocated?, verdict and
    evidence. Also returns contradictions found by the new evidence anywhere in the program area (all_words: every
    program-area word with evidence, for verify_all.py)."""
    g = Rom(gs1_path)
    d, size = g.data, len(g.data)
    gp = profiles.profile_gs1(gs1_path)
    end = gp["code_end"]
    cat, meta = wordmap.account(gs1_path, probe_path)
    info = {}
    relocs = build_gs1_reloc.classify(g, gp, info=info)
    probe = wordmap.load_probe(probe_path)
    excl = info["excluded"]
    sp = sprite_area(d, end)
    p = info["parts"]
    tables = p["runs"] | p["strided"]
    code = extended_code(d, info["code"], end, tables)
    stubs = reloc.stub_targets(g, end)
    flow = AccessFlow(g, end, code, stubs).run()
    sp_lo, sp_hi = sp["span"]
    other = {a for a, c in cat.items() if c in FORMAT_CATS}
    samples = info["samples"]
    slo = [x[0] for x in samples]

    def stop(b):
        j = bisect.bisect_right(slo, b) - 1
        return (b & ~3) in other or sp_lo <= b < sp_hi or (j >= 0 and b < samples[j][1]) or             info["text"]["data_start"] <= b < info["text"]["data_end"]
    narrow = flow.narrow_bytes({sp["T"]: sp["end"]}, stop)
    ptr_ev, data_ev = flow.words()
    users = stub_users(g, gp, info["code"])
    fspans = []
    for i, sp_ in filemap.file_spans(g).items():
        fspans += [(lo, hi, f"file {i}: {lab}") for lo, hi, lab in sp_ if lab.startswith("packed")]
    fspans.sort()
    flo = [x[0] for x in fspans]

    tracks = track_bytes(d, gp["song_table"])
    blob_bytes = {}                          # packed blobs that code passes to the decoder wrappers
    for o, (kind, insn) in flow.blobs.items():
        try:
            e = (hw_lz_span(d, o) if kind == "unpack-hw" else
                 (gfxlz.decompress_span if kind == "unpack-lz" else decompress_span)(d, o)[1])
        except (IndexError, ValueError):
            continue
        for b in range(o, min(e, size)):
            blob_bytes.setdefault(b, f"packed blob {o:#x}-{e:#x} passed to the {kind} wrapper at {insn:#010x}")
    lits = {((h + 4) & ~3) + (d[h] & 0xFF) * 4 for h in code if d[h + 1] & 0xF8 == 0x48}
    funcs = {e for e in flow.entries if e in info["code"] and reloc.is_prologue(d, e)}
    fver = {}
    if probe_path:                           # file words: the recorded file tour (fileverify.py)
        lang = os.path.splitext(os.path.basename(probe_path))[0]
        log = os.path.join(os.path.dirname(probe_path), f"files_{lang}.log")
        if os.path.exists(log):
            import fileverify
            want = {a for a, c in cat.items() if a >= end and (c.startswith(TARGETS))}
            fver = {a: v for a, v in fileverify.verify(gs1_path, log, probe_path)[0].items() if a in want}

    def evidence(a):
        w = u32(d, a)
        dat, ptr = [], []
        if a in sp["data"]:
            dat.append(("format", sp["data"][a]))
        if a in sp["ptr"]:
            ptr.append(("format", sp["ptr"][a]))
        if (a in code or a + 2 in code) and a not in lits:
            if a not in info["code"] and a + 2 not in info["code"]:
                dat.append(("code", "instruction (extended coverage: after mov ip,pc; bx / switch case)"))
            else:
                dat.append(("code", "instruction"))
        hits = [narrow[a + k] for k in range(4) if a + k in narrow]
        if hits:
            src, insn, grade = min(hits, key=lambda h: GRADES.index(h[2]))
            how = "exact" if src[0] == "at" else f"field T={src[1]:#x} stride {src[2]} +{src[3]:#x}, {grade} bound"
            dat.append(("code" if grade in ("exact", "parser", "mask") else f"code-{grade}",
                        f"byte/halfword read ({how}) at {insn:#010x}"))
        if a in ptr_ev:
            src, why = ptr_ev[a]
            ptr.append(("code", f"loaded and used as address ({src[0]}, {why[0]})"))
        if d[a - 4:a] == reloc.STUB and (a - 4) in users and w & 1:
            ptr.append(("code", f"engine stub jumped to by {users[a - 4]}"))
        if a in lits and w & 1 and (w & ~1) - ROM in funcs and set(flow.lit_use.get(a, ())) & {"arg", "stored",
                                                                                           "arg-deref", "jump"}:
            ptr.append(("code", f"literal = confirmed function {w & ~1:#x} + 1, passed on "
                                f"({'/'.join(sorted(flow.lit_use[a]))})"))
        if a in fver:
            v = fver[a]
            if v.startswith(("packed data", "colours", "read byte-wise")):
                dat.append(("probe", f"file tour: {v}"))
            elif v.startswith("format proof"):
                dat.append(("format", v))
        j = bisect.bisect_right(flo, a) - 1
        if j >= 0 and a + 4 <= fspans[j][1]:
            dat.append(("format", fspans[j][2]))
        bb = [blob_bytes[a + k] for k in range(4) if a + k in blob_bytes]
        if bb:
            dat.append(("format", bb[0]))
        tb = [tracks[a + k] for k in range(4) if a + k in tracks]
        if tb:
            dat.append(("format", f"m4a track stream at {tb[0]:#x} (read byte-wise)"))
        j = bisect.bisect_right(slo, a + 3) - 1
        if j >= 0 and a < samples[j][1]:
            dat.append(("format", f"m4a wave data {samples[j][0]:#x}-{samples[j][1]:#x}"))
        if cat.get(a) in KNOWN_PTR:
            ptr.append(("format" if cat[a] in ("mft", "music", "text-ptr") else "code", f"wordmap: {cat[a]}"))
        pe = probe.get(a)
        if pe and cat.get(a) != "music":           # m4a reads its own pointers byte-wise by design
            if pe[0] and not pe[1]:
                dat.append(("probe", f"read {pe[0]}x byte/halfword-wise only"))
            elif pe[1] and pe[2]:
                ptr.append(("probe", f"read 32-bit and used as address ({pe[2]}x)"))
        return dat, ptr

    res = {}
    for a, c in cat.items():
        mine = c.startswith(TARGETS) or a in excl
        dat, ptr = evidence(a) if (mine or a in relocs or a < end) else ([], [])
        r = a in relocs
        if dat and ptr:
            v = "conflict"
        elif dat:
            v = "data"
        elif ptr:
            v = "pointer"
        else:
            v = "unproven"
        bug = (v == "data" and r) or (v == "pointer" and not r)
        if mine or bug or all_words and a < end and (dat or ptr):
            res[a] = {"cat": c, "val": u32(d, a), "reloc": r, "verdict": v, "data": dat, "ptr": ptr,
                      "excl": a in excl, "mine": mine, "bug": bug, "dead": sp["dead"].get(a)}
    return res, {"sprite": sp, "probe": probe, "code": g.code, "fver": fver}


def summary(res):
    rows = collections.Counter()
    for a, x in res.items():
        if not x["mine"]:
            continue
        grp = "exclusion list" if x["excl"] else x["cat"]
        kind = x["verdict"]
        if kind in ("data", "pointer"):
            ev = x["data"] if kind == "data" else x["ptr"]
            kind += " (" + "/".join(sorted({e[0] for e in ev})) + ")"
        elif x["dead"]:
            kind = "structural (dead sprite-area word)"
        rows[(grp, kind)] += 1
    return rows


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--") and not x.endswith(".json")]
    res, meta = analyse(args[0], args[1] if len(args) > 1 else None)
    sp = meta["sprite"]
    print(f"sprite table {sp['T']:#x}: {sp['n']} records, area {sp['span'][0]:#x}-{sp['span'][1]:#x}, "
          f"{len(sp['ptr'])} pointer words, {len(sp['data'])} data words, {len(sp['problems'])} problems")
    for pr in sp["problems"][:10]:
        print("  problem:", pr)
    for (grp, kind), n in sorted(summary(res).items()):
        print(f"  {grp:28s} {kind:40s} {n:5d}")
    bugs = [a for a, x in res.items() if x["bug"]]
    print(f"contradictions with the build: {len(bugs)}")
    if "--json" in sys.argv:
        import json
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump({"code": meta["code"], "sprite": {k: sp[k] for k in ("T", "n", "end", "span", "problems")},
                   "words": {f"{a:06x}": x for a, x in res.items()}, "fver": {f"{a:06x}": v for a, v in meta["fver"].items()}},
                  open(out, "w"), indent=0)
    if "--list" in sys.argv:
        for a in sorted(res):
            x = res[a]
            if x["bug"] or x["verdict"] != "data" or "--all" in sys.argv:
                ev = (x["data"] or x["ptr"] or [("", x["dead"] or "")])[0]
                print(f"{a:06x} {x['val']:08x} {x['cat']:24s} {'R' if x['reloc'] else '-'} {'X' if x['excl'] else ' '} "
                      f"{x['verdict']:9s} {'BUG ' if x['bug'] else ''}{ev[0]}: {ev[1]}")
