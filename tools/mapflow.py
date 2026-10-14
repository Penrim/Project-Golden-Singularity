"""Code-use analysis of GS1's map code (the 96 compressed code files the engine unpacks to 0x02008000 and runs).

The build relocates every literal-pool word of a map code file whose value looks like a GS1 ROM address
(build_gs1_reloc.relocate_blob). This checks each pointer-like word of every unpacked file:
  code            part of a confirmed instruction (must not and does not get relocated)
  literal         loaded PC-relative by confirmed code; how the value is then used (typeflow use_lit):
                  addr / arg-deref / jump / swi = used as an address; arg / stored = passed on; cmp / arith = number
  other           neither (data inside the map code, or bytes never reached by the code coverage)
Calls into the engine go through the file's jump table (ldr r4,[pc]; bx r4; .word fn) and use the engine's
summaries ("argument k is dereferenced") from typeflow.Flow on the ROM.

  python mapflow.py GS1.gba
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles, reloc, typeflow
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

ROM, MAP_BASE = 0x08000000, 0x02008000


class _Deref(collections.defaultdict):
    """Local summaries plus the engine's for ("R", rom offset) keys."""
    def __init__(self, rom_deref):
        super().__init__(set)
        self.rom_deref = rom_deref

    def get(self, k, default=None):
        if isinstance(k, tuple) and k and k[0] == "R":
            return self.rom_deref.get(k[1], default)
        return super().get(k, default)


class MapFlow(typeflow.Flow):
    def __init__(self, romflow, blob, base=MAP_BASE):
        self.g, self.d, self.size, self.end = romflow.g, blob, len(blob), len(blob)
        self.base, self.rom, self.rom_size = base, romflow.d, romflow.size
        self.rom_code, self.rom_end, self.romflow = romflow.code, romflow.end, romflow
        self.lit_use = collections.defaultdict(collections.Counter)
        roots, o = set(), 0
        while self.d[o:o + 4] == reloc.STUB:
            w = struct.unpack_from("<I", blob, o + 4)[0]
            if base <= w < base + self.size:
                roots.add((w & ~1) - base)
            o += 8
        self.stub_end = o
        self.code = self._coverage(roots)
        self.md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        self.md.detail = True
        self.insns = self._decode()
        self.targets, self.entries = self._branches(roots)
        self.deref = _Deref(romflow.deref)
        self.ev_ptr = collections.defaultdict(set)
        self.ev_data = collections.defaultdict(set)

    def _coverage(self, roots):
        """Recursive descent from the jump-table entries; odd literals pointing at a push {.., lr} in this file
        (callbacks) become roots too, and so do odd words in data tables of the file that point at a prologue
        (event/NPC handler tables the engine calls), unless the code they lead to runs over such a table."""
        tables = set()
        for a in range(self.stub_end if hasattr(self, "stub_end") else 0, self.size - 3, 4):
            w = struct.unpack_from("<I", self.d, a)[0]
            t = (w & ~1) - self.base
            if w & 1 and 0 <= t < self.size and reloc.is_prologue(self.d, t):
                tables.add(a)
        for a in tables:
            t = (struct.unpack_from("<I", self.d, a)[0] & ~1) - self.base
            c = reloc.code_coverage(self.d, {t}, self.size)
            if not any(h & ~3 in tables for h in c):
                roots.add(t)
        code, done = set(), set()
        while roots - done:
            new = roots - done
            done |= new
            code |= reloc.code_coverage(self.d, new, self.size)
            for h in list(code):
                ins = self.d[h] | self.d[h + 1] << 8
                if ins & 0xF800 == 0x4800:
                    la = ((h + 4) & ~3) + (ins & 0xFF) * 4
                    if la + 4 <= self.size:
                        w = struct.unpack_from("<I", self.d, la)[0]
                        t = (w & ~1) - self.base
                        if w & 1 and 0 <= t < self.size and reloc.is_prologue(self.d, t):
                            roots.add(t)
        return code

    def resolve(self, t):
        """Jump-table stub of this file -> local function, or ("R", offset) of an engine function."""
        if isinstance(t, int) and 0 <= t and self.d[t:t + 4] == reloc.STUB:
            w = self.u32(t + 4)
            if w and w & 1:
                if self.base <= w < self.base + self.size:
                    return (w & ~1) - self.base
                if self.is_rom(w):
                    return ("R", self.romflow.resolve((w & ~1) - ROM))
        return t

    # ---- tables inside the map code file itself (addresses base .. base + size): evidence keyed ("L", offset)
    def is_local(self, v):
        return v is not None and self.base <= v < self.base + self.size

    def _add(self, a, b):
        for x, y in ((a, b), (b, a)):                 # local table + index (as typeflow does for ROM tables)
            if x and x[0] == "c" and self.is_local(x[1]) and y and y[0] in ("lin", "var"):
                ly = self._lin(y)
                return ("lidx", x[1], ly[1] if ly and y[0] == "lin" and ly[1] > 0 else 0)
            if x and x[0] == "lidx" and y and y[0] == "c" and y[1] is not None and abs(y[1]) < 0x1000:
                return ("lidx", x[1] + y[1], x[2])
        return super()._add(a, b)

    def _source(self, base, idx, disp, has_idx):
        src = super()._source(base, idx, disp, has_idx)
        if src:
            return src
        for b, i in ((base, idx), (idx, base)):
            if b and b[0] == "c" and self.is_local(b[1]):
                T = b[1] - self.base
                if b is base and not has_idx:
                    return ("L", T + disp)
                if i and i[0] == "c" and i[1] is not None:
                    return ("L", T + i[1] + disp)
                l = self._lin(i)
                return ("Lf", T, l[1], disp) if l and i[0] == "lin" and l[1] > 0 else ("Lf", T, 0, disp)
        if base and base[0] == "lidx" and not has_idx:
            return ("Lf", base[1] - self.base, base[2], disp)
        return None

    def local_reads(self):
        """Offsets of local words read by code: {offset: set of widths} (fields: every entry up to the next local
        label or 4096 entries; unknown stride: the addressed word only)."""
        labels = sorted({(v & ~1) - self.base for o, i in self.insns.items()
                         if i.mnemonic == "ldr" and "pc" in i.op_str
                         for v in [self.u32(((i.address + 4) & ~3) + i.operands[1].mem.disp - self.base)]
                         if self.is_local(v)})
        out = collections.defaultdict(set)
        for ev, wide in ((self.ev_data, False), (self.ev_ptr, True)):
            for src, why in ev.items():
                if not src or src[0] not in ("L", "Lf"):
                    continue
                width = 4 if wide else min(w[1] for w in why if w[0] == "narrow") if any(w[0] == "narrow" for w in why) else 4
                if src[0] == "L":
                    out[src[1] & ~3].add(width); continue
                _, T, s, off = src
                if not s:
                    out[(T + off) & ~3].add(width); continue
                import bisect
                k = bisect.bisect_right(labels, T)
                limit = labels[k] if k < len(labels) else self.size
                e = T
                while e + off < min(limit, self.size - 3) and (e - T) // s < 4096:
                    if (e + off) & ~3 in self.code:
                        break
                    out[(e + off) & ~3].add(width)
                    e += s
        return out

    def words(self):
        """Per pointer-like word of the file: category (see module doc)."""
        lits = {}
        for o, ins in self.insns.items():
            if ins.mnemonic == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == 3 \
                    and self.md.reg_name(ins.operands[1].mem.base) == "pc":
                lits[((ins.address + 4) & ~3) + ins.operands[1].mem.disp - self.base] = o
        out = {}
        for a in range(0, self.size - 3, 4):
            w = struct.unpack_from("<I", self.d, a)[0]
            if not self.is_rom(w):
                continue
            if a >= 4 and self.d[a - 4:a] == reloc.STUB:
                out[a] = ("jump table", None)              # ldr r4,[pc,#0]; bx r4; .word fn (file start or imports)
            elif a in lits:
                out[a] = ("literal", dict(self.lit_use.get(a, {})))
            elif a in self.code or a + 2 in self.code:
                out[a] = ("code", None)
            elif False:
                out[a] = ("literal", dict(self.lit_use.get(a, {})))
            else:
                out[a] = ("other", None)
        reads = self.local_reads()
        for a, (kind, u) in list(out.items()):
            if kind == "other" and a in reads:
                ptr = any(src[0] in ("L", "Lf") and (src[1] if src[0] == "L" else None) is not None
                          and src[1] & ~3 == a for src in self.ev_ptr)
                out[a] = ("table: used as address" if ptr else
                          "table: read as bytes/halfwords" if max(reads[a]) < 4 else "table: read as 32-bit", None)
        return out


def relocated(blob, size):
    """The words the build changes in an unpacked map code file (build_gs1_reloc.relocate_blob)."""
    import build_gs1_reloc
    nb, _ = build_gs1_reloc.relocate_blob(blob, size)
    return {a for a in range(0, len(blob) - 3, 4) if nb[a:a + 4] != blob[a:a + 4]}


def analyse(gs1_path, romflow=None):
    gp = profiles.profile_gs1(gs1_path)
    romflow = romflow or typeflow.Flow(gs1_path).run()
    res = {}
    for i in range(*gp["mapcode"]):
        mf = MapFlow(romflow, romflow.g.decompressed(i)).run()
        res[i] = (mf, mf.words())
    return res


ADDRESS_USES = {"addr", "arg-deref", "jump", "swi"}


def summary(res):
    c = collections.Counter()
    for i, (mf, words) in res.items():
        rel = relocated(mf.d, mf.rom_size)
        for a, (kind, uses) in words.items():
            if kind == "literal":
                u = set(uses or {})
                kind = ("literal: used as address" if u & ADDRESS_USES else
                        "literal: number (cmp/arith)" if u and u <= {"cmp", "arith"} else
                        "literal: passed on (arg/stored)" if u else "literal: loaded, use not seen")
            c[(kind, "relocated" if a in rel else "kept")] += 1
    return c


if __name__ == "__main__":
    res = analyse(sys.argv[1])
    for (k, r), n in sorted(summary(res).items()):
        print(f"  {k:36s} {r:9s} {n:6d}")
