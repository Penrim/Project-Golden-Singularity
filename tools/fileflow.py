"""How GS1's program uses each file of the Master File Table (static; complements filemap.py and the probe).

All file access goes through get_file(n) (`ldr r3,=MFT; lsls r0,#2; ldr r0,[r3,r0]; bx lr`). Following the result
through the code (typeflow.Flow with a file value) shows what happens to every file:
  unpack-gs     passed to the routine 0x08005340 copies to RAM and runs (Golden Sun format 0/1 decoder)
  unpack-lz     passed to the routine 0x080053E8 copies to RAM and runs (graphics LZ, ROM 0x08001B70)
  copy          raw copy by the IWRAM routine at 0x03001388 (dst r0, src r1, size r2), with its destination
  read          direct loads from the file (width, offset)
  arg           passed on to another function (its argument)
The file number is a constant, a field of a ROM table (all entries of that field) or a function argument
(resolved at the callers).

  python fileflow.py GS1.gba
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import typeflow
from gsfs import Rom

ROM = 0x08000000


def _find_getfile(f):
    for o, ins in f.insns.items():
        if ins.mnemonic == "ldr" and "pc" in ins.op_str:
            v = f.u32(((ins.address + 4) & ~3) + ins.operands[1].mem.disp - ROM)
            if v == ROM + f.g.mft_off:
                nxt = [f.insns.get(o + 2), f.insns.get(o + 4), f.insns.get(o + 6)]
                if all(nxt) and nxt[1].mnemonic == "ldr" and nxt[2].mnemonic == "bx":
                    return o
    raise LookupError("get_file not found")




def _copy_routines(f):
    """(wrapper entry -> kind): functions that DMA-copy one of the two decoder routines to RAM and run it with
    (src, dst). The decoders are found by size and content: the GS format 0/1 decoder (0x2C4 bytes) and the
    graphics LZ (0x258 bytes, the ARM routine gfxlz.py is ported from). Other copied routines (0x54-0x7C bytes)
    are not decoders."""
    out = {}
    for o, ins in f.insns.items():
        if ins.mnemonic != "push" or "lr" not in ins.op_str:
            continue
        body = [f.insns.get(o + 2 * k) for k in range(24)]
        lits = [f.u32(((i.address + 4) & ~3) + i.operands[1].mem.disp - ROM) for i in body
                if i is not None and i.mnemonic == "ldr" and "pc" in i.op_str]
        if 0x040000D4 not in lits:
            continue
        if 0x2C4 in lits and any(v is not None and ROM <= v < ROM + 0x8000 for v in lits):
            out[o] = "unpack-gs"
        elif 0x258 in lits and any(v is not None and ROM <= v < ROM + 0x8000 for v in lits):
            out[o] = "unpack-lz"
    return out


class FileFlow(typeflow.Flow):
    def __init__(self, rom):
        super().__init__(rom)
        self.getfile = _find_getfile(self)
        self.wrappers = _copy_routines(self)
        self.veneers = {o: i.op_str for o, i in self.insns.items()
                        if i.mnemonic == "bx" and i.op_str not in ("lr",) and o in self.entries}
        self.uses = collections.defaultdict(collections.Counter)   # file source -> Counter of uses
        self.sites = []                                            # (call address, file source, function)
        self.callargs = collections.defaultdict(collections.Counter)  # (function, arg) -> Counter of sources

    def _src(self, v):
        if v is None:
            return ("?",)
        if v[0] == "c" and v[1] is not None and 0 <= v[1] < 4096:
            return ("n", v[1])
        if v[0] == "ld" and v[1] and v[1][0] == "fld":
            return ("tab",) + tuple(v[1][1:])
        if v[0] == "ld" and v[1] and v[1][0] == "at":
            return ("at", v[1][1])
        if v[0] == "par":
            return ("par", v[1])
        if v[0] == "fbase":
            return ("base", v[1])
        return ("?",)

    def _step(self, ins, regs, func, record=True):
        m = ins.mnemonic
        if record and m == "bl" and ins.operands:
            t = self.resolve(ins.operands[0].imm - ROM)
            for k in range(4):                        # argument values per callee (resolves file-number parameters)
                self.callargs[(t, k)][self._src(regs.get(f"r{k}"))] += 1
            files = {k: regs.get(f"r{k}") for k in range(4) if (regs.get(f"r{k}") or (None,))[0] == "file"}
            if files:
                kind = self.wrappers.get(t)
                if t in self.veneers:
                    target = regs.get(self.veneers[t])
                    if target and target[0] == "c" and target[1] == 0x03001388 and 1 in files:
                        dst = regs.get("r0")
                        area = (dst[1] >> 24) if dst and dst[0] == "c" and dst[1] is not None else None
                        n = regs.get("r2")
                        self._use(files[1], ("copy", {5: "palette", 6: "vram", 7: "oam"}.get(area, f"ram{area}"),
                                             files[1][2], n[1] if n and n[0] == "c" else None), func)
                        files = {}
                for k, v in files.items():
                    self._use(v, (kind, v[2]) if kind and k == 0 else ("arg", t, k, v[2]), func)
        if record and m.startswith("ldr") and len(ins.operands) == 2 and ins.operands[1].type == 3:
            b = regs.get(self.md.reg_name(ins.operands[1].mem.base))
            if b and b[0] == "file":
                self._use(b, ("read", m, None if b[2] is None else b[2] + ins.operands[1].mem.disp), func)
        r = super()._step(ins, regs, func, record)
        if m == "bl" and ins.operands and self.resolve(ins.operands[0].imm - ROM) == self.getfile:
            regs["r0"] = ("file", self._last_src, 0)
            if record:
                self.sites.append((ins.address, self._last_src, func))
        return r

    def _use(self, v, what, func):
        src = v[1]
        if src and src[0] == "par":
            src = ("par", func, src[1])
        self.uses[src][what] += 1

    def _pass(self):
        orig = super()._step
        def track(ins, regs, func, record=True):
            if ins.mnemonic == "bl" and ins.operands and self.resolve(ins.operands[0].imm - ROM) == self.getfile:
                self._last_src = self._src(regs.get("r0"))
                if self._last_src == ("?",):
                    self._last_src = ("?", ins.address)
            return orig(ins, regs, func, record)
        super_step = typeflow.Flow._step
        typeflow.Flow._step = lambda s, ins, regs, func, record=True: track(ins, regs, func, record)
        try:
            super()._pass()
        finally:
            typeflow.Flow._step = super_step

    def _add(self, a, b):
        for x, y in ((a, b), (b, a)):                 # small constant + unknown = a file-number range "base + i"
            if x and x[0] == "c" and x[1] is not None and 0 < x[1] < 4096 and y and y[0] in ("var", "lin", "ld"):
                return ("fbase", x[1])
        for x, y in ((a, b), (b, a)):
            if x and x[0] == "file":                  # file + constant keeps the offset, + anything else: unknown
                off = x[2] + y[1] if (y and y[0] == "c" and y[1] is not None and x[2] is not None) else None
                return ("file", x[1], off)
        return super()._add(a, b)


    def files_of(self, src, depth=0):
        """File numbers a source can stand for: a constant, every entry of a table field, or (for a function
        argument) the union over the callers. Unresolvable parts are returned in the second set."""
        if src[0] == "n":
            return {src[1]}, set()
        if src[0] == "tab":
            T, stride, off = src[1], src[2], src[3]
            out, i = set(), 0
            while stride and i < 4096:
                v = self.u32(T + i * stride + off)
                if v is None or v >= len(self.g.entries):
                    break
                out.add(v); i += 1
            return out, set() if stride else {src}
        if src[0] == "par" and depth < 6:
            out, open_ = set(), set()
            for s2 in self.callargs.get((src[1], src[2]), {}):
                if s2[0] == "par" and len(s2) == 2:
                    s2 = ("par", None, s2[1])
                if s2[0] == "par" and s2[1] is None:
                    open_.add(src); continue
                a, b = self.files_of(s2, depth + 1)
                out |= a; open_ |= b
            if not self.callargs.get((src[1], src[2])):
                open_.add(src)
            return out, open_
        return set(), {src}

    def parts(self):
        """file number -> Counter of (route, offset[, size]) from every resolvable source."""
        out = collections.defaultdict(collections.Counter)
        unresolved = collections.Counter()
        for src, uses in self.uses.items():
            files, open_ = self.files_of(src)
            for k in files:
                out[k].update(uses)
            for o in open_:
                unresolved[o] += sum(uses.values())
        return out, unresolved


if __name__ == "__main__":
    ff = FileFlow(sys.argv[1]).run(rounds=2)
    ff.sites = sorted(set(ff.sites))
    print(f"get_file at {ROM + ff.getfile:08x}; unpack wrappers: " +
          ", ".join(f"{ROM + o:08x}={k}" for o, k in sorted(ff.wrappers.items())))
    for src, c in sorted(ff.uses.items(), key=lambda kv: str(kv[0])):
        print(src, dict(c))
