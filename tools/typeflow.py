"""Data-type evidence for GS1's ROM tables, from how the program code uses them (static, no emulator).

An abstract interpreter walks every confirmed Thumb instruction (reloc.strict_code) and tracks per register where
its value came from:
  ("c", v)                 constant (from a literal pool, movs, adds ...)
  ("idx", T, s)            T + index * s (T = ROM address, s = element size; s = 0: unknown)
  ("ld", src)              a word loaded from src: ("at", a) = exact ROM word a, ("fld", T, s, off) = field of a table
  ("par", k)               the function's k-th argument (r0..r3 at the entry)
Evidence:
  pointer: a loaded word is used as an address (load/store base, BIOS decompress/copy source, DMA source,
           bx/mov pc, or an argument of a function that dereferences that argument)
  data:    code reads the word (or a field) byte- or halfword-wise
A field (T, s, off) is applied to the whole table: entries T + i*s + off while they stay pointer-like (or 0).
Calls are summarised per function: "argument k is dereferenced" (fixpoint over the call graph).

  python typeflow.py GS1.gba         (prints counts; used by wordmap.py)
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG
from gsfs import Rom
import profiles, reloc

ROM = 0x08000000
IO_DMA = range(0x040000B0, 0x040000E0)
SWI_SRC = {0x0B, 0x0C, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18}   # CpuSet, CpuFastSet, decompressors


class Flow:
    def __init__(self, rom, code_end=None, code=None, stubs=None):
        """rom: path or gsfs.Rom; code/stubs: precomputed reloc.strict_code result and stub targets (optional)."""
        self.g = Rom(rom) if isinstance(rom, str) else rom
        self.d = self.g.data
        self.size = len(self.d)
        self.end = code_end if code_end is not None else profiles.profile_gs1(rom)["code_end"]
        if code is None:
            parts = {}
            reloc.analyse(self.g, self.end, parts=parts)
            stubs = reloc.stub_targets(self.g, self.end)
            code = reloc.strict_code(self.d, stubs, self.end, parts["roots"] - stubs, parts["runs"] | parts["strided"])
        self.code = code
        self.md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        self.md.detail = True
        self.insns = self._decode()
        self.targets, self.entries = self._branches(stubs if stubs is not None else reloc.stub_targets(self.g, self.end))
        self.deref = collections.defaultdict(set)     # function entry -> argument numbers it dereferences
        self.ev_ptr = collections.defaultdict(set)    # source -> reasons ("at", a) / ("fld", T, s, off)
        self.ev_data = collections.defaultdict(set)

    # ------------------------------------------------------------------ decoding
    def _decode(self):
        out = {}
        hs = sorted(self.code)
        i = 0
        while i < len(hs):
            j = i
            while j + 1 < len(hs) and hs[j + 1] == hs[j] + 2:
                j += 1
            a, b = hs[i], hs[j] + 2
            for ins in self.md.disasm(self.d[a:b + 2], ROM + a):
                o = ins.address - ROM
                if o >= b:
                    break
                if o in self.code:
                    out[o] = ins
            i = j + 1
        return out

    def _branches(self, stubs):
        targets, entries = set(), set(stubs)
        for o, ins in self.insns.items():
            if ins.mnemonic in ("bl",) and ins.operands and ins.operands[0].type == ARM_OP_IMM:
                t = ins.operands[0].imm - ROM
                entries.add(t); entries.add(self.resolve(t))
            elif ins.mnemonic.startswith("b") and ins.mnemonic not in ("bx", "bic", "bics", "bkpt") \
                    and ins.operands and ins.operands[0].type == ARM_OP_IMM:
                targets.add(ins.operands[0].imm - ROM)
        return targets, entries

    def resolve(self, t):
        """Engine jump-table stub (ldr r4,[pc]; bx r4; .word fn) -> the function it jumps to."""
        if self.d[t:t + 4] == reloc.STUB:
            w = self.u32(t + 4)
            if w and w & 1 and self.is_rom(w):
                return (w & ~1) - ROM
        return t

    # ------------------------------------------------------------------ evidence helpers
    def u32(self, a):
        return struct.unpack_from("<I", self.d, a)[0] if 0 <= a <= self.size - 4 else None

    def is_rom(self, v):
        return v is not None and ROM <= v < ROM + self.size

    def mark_ptr(self, val, why):
        if val and val[0] == "ld":
            if self._rec and val[1]:
                self.ev_ptr[val[1]].add(why)
            return True
        return False

    # ------------------------------------------------------------------ interpretation
    def run(self, rounds=3):
        for r in range(rounds):
            before = sum(len(v) for v in self.deref.values())
            self.ev_ptr.clear(); self.ev_data.clear()
            self._pass()
            if sum(len(v) for v in self.deref.values()) == before and r:
                break
        return self

    def _blocks(self):
        """Basic blocks over the confirmed instructions with successor edges (BL is not a block end)."""
        order = sorted(self.insns)
        starts = set(self.entries) | set(self.targets)
        term = {}
        for o in order:
            ins = self.insns[o]
            m = ins.mnemonic
            end = m in ("b", "bx") or (m == "pop" and "pc" in ins.op_str) or (m == "mov" and ins.op_str.startswith("pc"))
            cond = m.startswith("b") and m not in ("b", "bl", "bx", "bic", "bics", "bkpt") and len(m) <= 4
            term[o] = (end, cond)
            if end or cond:
                starts.add(o + 2)
        blocks, cur = {}, None
        for o in order:
            if o in starts or cur is None or o != prev + (4 if self.insns[prev].mnemonic == "bl" else 2):
                cur = o
                blocks[cur] = []
            blocks[cur].append(o)
            prev = o
        succ = {}
        for b, os_ in blocks.items():
            last = os_[-1]
            ins = self.insns[last]
            end, cond = term[last]
            nxt = last + (4 if ins.mnemonic == "bl" else 2)
            s_ = []
            if ins.mnemonic.startswith("b") and ins.mnemonic not in ("bl", "bx", "bic", "bics") and ins.operands                     and ins.operands[0].type == ARM_OP_IMM:
                s_.append(ins.operands[0].imm - ROM)
            if not end and nxt in blocks:
                s_.append(nxt)
            succ[b] = [x for x in s_ if x in blocks]
        return blocks, succ

    def _pass(self):
        if not hasattr(self, "_cfg"):
            self._cfg = self._blocks()
        blocks, succ = self._cfg
        state = {b: {f"r{k}": ("par", k) for k in range(4)} for b in blocks if b in self.entries}
        owner = {b: b for b in blocks if b in self.entries}
        work = list(state)
        seen = collections.Counter()
        while work:
            b = work.pop()
            seen[b] += 1
            regs = dict(state[b])
            for o in blocks[b]:
                self._step(self.insns[o], regs, owner.get(b), record=False)
            for t in succ[b]:
                if t in self.entries:
                    continue
                if t not in state:
                    state[t] = dict(regs); owner.setdefault(t, owner.get(b)); work.append(t)
                else:
                    merged = {k: v for k, v in state[t].items() if regs.get(k) == v}
                    if merged != state[t] and seen[t] < 8:
                        state[t] = merged; work.append(t)
        for b, os_ in blocks.items():                 # final pass: record evidence with the settled states
            regs = dict(state.get(b, {}))
            for o in os_:
                self._step(self.insns[o], regs, owner.get(b), record=True)

    def _reg(self, regs, op):
        return regs.get(self.md.reg_name(op.reg))

    def _base(self, regs, mem):
        base = regs.get(self.md.reg_name(mem.base)) if mem.base else None
        if self.md.reg_name(mem.base) == "pc":
            return None
        idx = self._val(regs, self.md.reg_name(mem.index), mem) if mem.index else None
        return base, idx, mem.disp, bool(mem.index)

    def _step(self, ins, regs, func, record=True):
        self._rec = record
        m, ops = ins.mnemonic, ins.operands
        name = lambda op: self.md.reg_name(op.reg)
        dst = name(ops[0]) if ops and ops[0].type == ARM_OP_REG else None
        # ---- loads
        if m in ("ldr", "ldrh", "ldrb", "ldrsh", "ldrsb") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            if self.md.reg_name(mem.base) == "pc":                    # literal pool
                la = ((ins.address + 4) & ~3) + mem.disp - ROM
                regs[dst] = ("c", self.u32(la))
                return
            base, idx, disp, has_idx = self._base(regs, mem)
            width = 4 if m == "ldr" else 2 if m in ("ldrh", "ldrsh") else 1
            src = self._source(base, idx, disp, has_idx)
            self._deref(base, idx, func, ins)
            if src and width < 4 and self._rec:
                self.ev_data[src].add(("narrow", width, ins.address))
            regs[dst] = ("ld", src) if (src and width == 4) else ("var", ins.address, dst)
            return
        # ---- stores
        if m in ("str", "strh", "strb") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            base, idx, disp, _ = self._base(regs, mem)
            self._deref(base, idx, func, ins)
            if base and base[0] == "c" and base[1] is not None and base[1] + disp in IO_DMA and m == "str":
                self.mark_ptr(regs.get(dst), ("dma", ins.address))
            regs_val = regs.get(dst)
            return
        # ---- calls
        if m == "bl" and ops and ops[0].type == ARM_OP_IMM:
            t = self.resolve(ops[0].imm - ROM)
            veneer = self.insns.get(t)
            if veneer is not None and veneer.mnemonic == "bx" and veneer.op_str != "lr":
                self.mark_ptr(regs.get(veneer.op_str), ("call", ins.address))     # bl _call_via_rN
            for k in sorted(self.deref.get(t, ())):
                v = regs.get(f"r{k}")
                if not self.mark_ptr(v, ("arg", t, k)) and v and v[0] == "par" and func is not None:
                    self.deref[func].add(v[1])
            for r in ("r0", "r1", "r2", "r3", "r12", "lr"):
                regs.pop(r, None)
            return
        if m == "svc" and ops:
            if ops[0].imm in SWI_SRC:
                v = regs.get("r0")
                if not self.mark_ptr(v, ("swi", ins.address)) and v and v[0] == "par" and func is not None:
                    self.deref[func].add(v[1])
            for r in ("r0", "r1", "r3"):
                regs.pop(r, None)
            return
        if m == "bx" or (m == "mov" and dst == "pc"):
            v = regs.get(name(ops[-1]))
            self.mark_ptr(v, ("jump", ins.address))
            if v and v[0] == "par" and func is not None and m == "bx" and name(ops[-1]) != "lr":
                self.deref[func].add(v[1])
            return
        # ---- arithmetic / moves (unknown values get an identity so that index arithmetic such as
        #      (i << 3) - i, (i << 1) + i is recognised as 7*i, 3*i)
        if dst is None:
            return
        srcs = list(ops[1:])
        val_of = lambda op: ("c", op.imm) if op.type == ARM_OP_IMM else self._val(regs, name(op), ins)
        val = None
        if m in ("movs", "mov") and len(srcs) == 1:
            val = val_of(srcs[0])
        elif m in ("adds", "add") and srcs:
            a = self._val(regs, dst, ins) if len(srcs) == 1 else val_of(srcs[0])
            val = self._add(a, val_of(srcs[-1]))
        elif m in ("subs", "sub") and srcs:
            a = self._val(regs, dst, ins) if len(srcs) == 1 else val_of(srcs[0])
            val = self._sub(a, val_of(srcs[-1]))
        elif m == "lsls" and len(srcs) == 2 and srcs[1].type == ARM_OP_IMM:
            val = self._scale(val_of(srcs[0]), 1 << srcs[1].imm)
        elif m in ("muls", "mul") and srcs:
            a, b = self._val(regs, dst, ins), val_of(srcs[-1])
            if b and b[0] == "c":
                val = self._scale(a, b[1])
            elif a and a[0] == "c":
                val = self._scale(b, a[1])
        regs[dst] = val if val is not None else ("var", ins.address, dst)

    def _val(self, regs, r, ins):
        """Register value; an unknown register gets an identity on first use."""
        v = regs.get(r)
        if v is None:
            v = regs[r] = ("var", ins.address if hasattr(ins, "address") else 0, r)
        return v

    @staticmethod
    def _lin(v):
        """(identity, factor) of a linear index value, else None."""
        if v and v[0] == "var":
            return v, 1
        if v and v[0] == "lin":
            return v[1], v[2]
        return None

    def _scale(self, a, k):
        if a is None or k is None:
            return None
        if a[0] == "c" and a[1] is not None:
            return ("c", (a[1] * k) & 0xFFFFFFFF)
        l = self._lin(a)
        return ("lin", l[0], l[1] * k) if l else None

    def _sub(self, a, b):
        if b and b[0] == "c" and b[1] is not None:
            return self._add(a, ("c", -b[1]))
        la, lb = self._lin(a), self._lin(b)
        if la and lb and la[0] == lb[0]:
            return ("lin", la[0], la[1] - lb[1])
        if a and a[0] in ("ld", "par"):
            return a
        return None

    def _add(self, a, b):
        if b and b[0] == "c" and b[1] == 0:
            return a
        if a and b and a[0] == "c" and b[0] == "c" and a[1] is not None and b[1] is not None:
            return ("c", (a[1] + b[1]) & 0xFFFFFFFF)
        for x, y in ((a, b), (b, a)):                 # pointer/argument plus offset or index keeps its origin
            if x and x[0] in ("ld", "par") and (y is None or y[0] in ("c", "lin", "var")):
                return x
        la, lb = self._lin(a), self._lin(b)
        if la and lb and la[0] == lb[0]:
            return ("lin", la[0], la[1] + lb[1])
        for x, y in ((a, b), (b, a)):
            if x and x[0] == "c" and self.is_rom(x[1]):
                if y and y[0] == "c":
                    return ("c", x[1] + (y[1] or 0))
                ly = self._lin(y)
                return ("idx", x[1], ly[1] if ly and y[0] == "lin" and ly[1] > 0 else 0)
            if x and x[0] == "idx" and y and y[0] == "c" and y[1] is not None and abs(y[1]) < 0x1000:
                return ("idx", x[1] + y[1], x[2])
            if x and x[0] == "idx":
                return ("idx", x[1], 0)
        return None

    def _source(self, base, idx, disp, has_idx):
        """Which ROM word a load reads: exact address ("at") or table field ("fld", T, stride, offset);
        stride 0 = unknown (then only the addressed word itself counts)."""
        for b, i in ((base, idx), (idx, base)):
            if b and b[0] == "c" and self.is_rom(b[1]):
                T = b[1] - ROM
                if b is base and not has_idx:
                    return ("at", T + disp)
                if i and i[0] == "c" and i[1] is not None:
                    return ("at", T + i[1] + disp)
                l = self._lin(i)
                if not (l and i[0] == "lin" and l[1] > 0):
                    return None                       # unknown index: which word is read is not known
                return ("fld", T, l[1], disp)
        if base and base[0] == "idx" and base[2] > 0 and not has_idx:
            return ("fld", base[1] - ROM, base[2], disp)
        return None

    def _deref(self, base, idx, func, ins):
        """The base register of a load/store was itself loaded from ROM -> that word is a pointer."""
        for v in (base, idx):
            if not v:
                continue
            if v[0] == "ld":
                self.mark_ptr(v, ("deref", ins.address))
            elif v[0] == "par" and func is not None:
                self.deref[func].add(v[1])

    # ------------------------------------------------------------------ results
    def words(self):
        """word offset -> ("ptr"|"data", reason). Fields are spread over their table."""
        out_p, out_d = {}, {}
        for src, why in self.ev_ptr.items():
            for a in self._spread(src, want_ptr=True):
                out_p.setdefault(a, (src, sorted(why)[0]))
        for src, why in self.ev_data.items():
            for a in self._spread(src, want_ptr=False):
                out_d.setdefault(a, (src, sorted(why)[0]))
        return out_p, out_d

    def labels(self):
        """Table starts: every ROM address that confirmed code loads as a constant (as disassemblers do)."""
        if not hasattr(self, "_labels"):
            lab = set()
            for o, ins in self.insns.items():
                if ins.mnemonic == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == ARM_OP_MEM                         and self.md.reg_name(ins.operands[1].mem.base) == "pc":
                    v = self.u32(((ins.address + 4) & ~3) + ins.operands[1].mem.disp - ROM)
                    if self.is_rom(v):
                        lab.add((v & ~1) - ROM)
            self._labels = sorted(lab)
        return self._labels

    def _spread(self, src, want_ptr):
        """Words covered by a source. A table field (T, s, off) covers T + i*s + off up to the next label after T
        (at most 4096 entries); pointer fields also stop at the first entry that is neither pointer-like nor 0."""
        import bisect
        if src[0] == "at":
            a = src[1] & ~3
            return [a] if 0 <= a < self.size - 3 else []
        _, T, s, off = src
        start = T + off
        if not s:
            return [start & ~3] if 0 <= start < self.size - 3 else []
        lab = self.labels()
        k = bisect.bisect_right(lab, T)
        limit = lab[k] if k < len(lab) else self.end
        out, i = [], 0
        while i < 4096:
            e = T + i * s
            if e >= limit or e + off > self.size - 4:
                break
            a = (e + off) & ~3
            if a in self.code or a + 2 in self.code:   # a table never runs over code
                break
            w = self.u32(a)
            if want_ptr and not (w == 0 or self.is_rom(w)):
                break
            out.append(a)
            i += 1
        return out


if __name__ == "__main__":
    f = Flow(sys.argv[1]).run()
    p, dta = f.words()
    d = f.d
    pl = lambda a: ROM <= struct.unpack_from("<I", d, a)[0] < ROM + len(d)
    print("functions with dereferenced arguments:", sum(1 for v in f.deref.values() if v))
    print("pointer evidence (pointer-like words):", sum(1 for a in p if pl(a)))
    print("data evidence (pointer-like words):", sum(1 for a in dta if pl(a)))
    print("both:", sum(1 for a in p if a in dta and pl(a)))
