"""typeflow.Flow extended for pointer TABLES: tables reached through other tables, through RAM variables and
objects, through function results and through function arguments (static, no emulator; used by tableproof.py).

Sources (where a loaded word comes from):
  ("at", a) / ("fld", T, s, off)   ROM word / field of a ROM table (as in typeflow)
  ("g", A, s, off)                 RAM word A + i*s + off (s = 0: exactly A + off)
  ("sub", parent, s, off)          the word at (value of the parent word) + i*s + off: a table that a pointer from
                                   another table (or from RAM) points to; nests (sprite info -> frame table -> frame)
  ("parf", k, s, off)              the word at argument k + i*s + off (function summaries only)
Values: typeflow's plus ("ld", src, s, off) / ("par", k, s, off) = loaded pointer / argument + index*s + off
(s = -1 or off = None: unknown); ("lin", id, k, c) = k*id + c; ("idx", T, s) also for RAM bases. A pointer walked
in a loop (p += 4) becomes an index (stride = gcd of the steps).
Additions to typeflow:
  return values   a function whose every return leaves the same address / table element / loaded word in r0
                  (e.g. the sprite getter 0x08185008: 0x08185024 + id * 0x14) gives it to its callers
  summaries       "the word at path P (rooted at an argument) is dereferenced / read narrow / receives value V";
                  the callers substitute their actual arguments (fixpoint over the call graph)
  RAM links       a value stored to a RAM word (global or object field, keyed by its access path) and a load of
                  the same path elsewhere: what the program does with the loaded value applies to every ROM value
                  stored there (obj+8 := sprite frame table ... decompress(obj+8[frame]))
  stack slots     push/pop and str/ldr [sp, #n] keep register values; cleared when a stack address escapes
  ldm             loads every listed register (typeflow keeps stale values there)
Spreading a nested ROM source needs table bounds: entries run from the target while pointer-like (pointer evidence),
never over code, and stop at the next boundary = a code label, an MFT file start, or the target of any other
pointer with evidence. Every instance must hold a pointer-like word (else the field has no common layout: dropped);
MFT files are never spread into (different formats). Narrow reads through a walked pointer (s > 0) are only
reported as candidates (`walked`): the stream length is not known.

  python tableflow.py GS1.gba
"""
import bisect, collections, math, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG
import typeflow

ROM = 0x08000000
LOADS = ("ldr", "ldrh", "ldrb", "ldrsh", "ldrsb")
CONFLICT = ("conflict",)


def root(src):
    while src and src[0] == "sub":
        src = src[1]
    return src


def is_ram(v):
    return v is not None and (0x02000000 <= v < 0x02040000 or 0x03000000 <= v < 0x03008000)


def depth(src):
    n = 0
    while src and src[0] == "sub":
        src, n = src[1], n + 1
    return n


class TableFlow(typeflow.Flow):
    _gcd = True

    def __init__(self, *a, may=True, gcd=True, **kw):
        """may: keep a table word / argument at a merge with an unknown value (if (!p) p = default);
        gcd: RAM paths with two strides (objects + 0x38*i + 0x28 + 4*j) are keyed by their gcd."""
        super().__init__(*a, **kw)
        self.may, self.gcd = may, gcd
        self.psum = collections.defaultdict(set)     # function -> {(path, "ptr" | "data" | ("store", value))}
        self.ret = {}                                # function -> r0 value at every return (or CONFLICT)
        self.stores = collections.defaultdict(set)   # RAM source -> values stored there
        self.ram_ev = collections.defaultdict(set)   # RAM-rooted source -> {"ptr", "data"}
        self._retv = collections.defaultdict(set)
        self._func, self._rec = None, False
        self.bounds, self.walked, self._walk, self.inconsistent = [], {}, False, {}
        self.trace = {}                               # debugging: offset -> registers before that instruction

    # ------------------------------------------------------------------ fixpoint
    def run(self, rounds=8):
        TableFlow._gcd = self.gcd
        for r in range(rounds):
            before = (sum(len(v) for v in self.deref.values()), sum(len(v) for v in self.psum.values()),
                      dict(self.ret))
            self.ev_ptr.clear(); self.ev_data.clear(); self.stores.clear(); self.ram_ev.clear()
            self._retv = collections.defaultdict(set)
            self._pass()
            self.ret = {f: (next(iter(v)) if len(v) == 1 else CONFLICT) for f, v in self._retv.items()}
            after = (sum(len(v) for v in self.deref.values()), sum(len(v) for v in self.psum.values()), self.ret)
            if before == after and r:
                break
        self._resolve()
        return self

    @staticmethod
    def _ext(v):
        return (v[2], v[3]) if len(v) > 3 else (0, 0)

    def _merge(self, a, b):
        """Join of two abstract values at a control-flow merge (None = unknown)."""
        if a == b:
            return a
        pa = a is not None and a[0] in ("ld", "par") and a[1] is not None
        pb = b is not None and b[0] in ("ld", "par") and b[1] is not None
        if pa != pb and self.may:              # may-analysis: a table word / argument reaching this point on
            return a if pa else b                     # one path keeps its identity (if (!p) p = default)
        if not a or not b:
            return None
        if a[0] == b[0] and a[0] in ("ld", "par") and a[1] == b[1]:
            s1, o1 = self._ext(a)
            s2, o2 = self._ext(b)
            if o1 is None or o2 is None or s1 < 0 or s2 < 0:
                return (a[0], a[1], -1, None)
            g = math.gcd(math.gcd(s1, s2), abs(o1 - o2))
            return (a[0], a[1], g, o1 % g if g else o1)
        if a[0] in ("c", "idx") and b[0] in ("c", "idx") and self._addr(a[1]) and self._addr(b[1]) \
                and abs(a[1] - b[1]) < 0x1000:       # a pointer walking a table
            s1 = a[2] if a[0] == "idx" else 0
            s2 = b[2] if b[0] == "idx" else 0
            g = math.gcd(math.gcd(s1, s2), abs(a[1] - b[1]))
            if g and g % 2 == 0:
                return ("idx", min(a[1], b[1]), g)
        return None

    def _addr(self, v):
        return v is not None and (self.is_rom(v) or is_ram(v))

    def _pass(self):
        if not hasattr(self, "_cfg"):
            self._cfg = self._blocks()
        blocks, succ = self._cfg
        init = {f"r{k}": ("par", k, 0, 0) for k in range(4)}
        init["sp"] = ("sp", 0)
        if not hasattr(self, "_orphans"):
            # blocks no edge reaches: functions called only through pointers (push {.., lr} first: a function of
            # its own) and switch cases (jump-table targets: analysed without an owner, so no summaries)
            reached = {t for ss in succ.values() for t in ss}
            self._orphans = {b for b in blocks if b not in reached and b not in self.entries}
            self._fentries = set(self.entries) | {b for b in self._orphans if self.insns[b].mnemonic == "push"
                                                  and "lr" in self.insns[b].op_str}
        state = {b: dict(init) for b in blocks if b in self.entries or b in self._orphans}
        owner = {b: b for b in blocks if b in self._fentries}
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
                    merged = {}
                    for k, v in state[t].items():
                        m = self._merge(v, regs.get(k))
                        if m is not None:
                            merged[k] = m
                    if merged != state[t] and seen[t] < 8:
                        state[t] = merged; work.append(t)
        for b, os_ in blocks.items():
            regs = dict(state.get(b, {}))
            for o in os_:
                self._step(self.insns[o], regs, owner.get(b), record=True)

    # ------------------------------------------------------------------ value algebra
    @staticmethod
    def _lin(v):
        """(identity, factor, offset) of an integer value; an argument or loaded word can be an index too."""
        if not v:
            return None
        if v[0] == "var":
            return v, 1, 0
        if v[0] == "lin":
            return v[1], v[2], (v[3] if len(v) > 3 else 0)
        if v[0] in ("par", "ld"):
            return v[:2], 1, 0
        return None

    def _addc(self, x, c):
        """x + constant c."""
        if x is None or c is None:
            return None
        c = c - (1 << 32) if c >= 0x80000000 else c
        small = abs(c) < 0x10000
        if x[0] == "c":
            return ("c", (x[1] + c) & 0xFFFFFFFF) if x[1] is not None else None
        if x[0] in ("ld", "par"):
            s, o = self._ext(x)
            if small:
                return (x[0], x[1], s, None if o is None else o + c)
            return ("idx", c & 0xFFFFFFFF, 0) if self._addr(c & 0xFFFFFFFF) else None   # table + loaded offset
        if x[0] == "idx":                            # an index never reaches before the table: -4 = entry - 1
            return ("idx", x[1] + (c % x[2] if c < 0 and x[2] > 0 else c), x[2]) if small else None
        if x[0] == "spa":
            return ("spa", x[1] + c) if small else None
        l = self._lin(x)
        if l:
            if small:
                return ("lin", l[0], l[1], l[2] + c)
            k = l[1] if x[0] == "lin" else 0
            return ("idx", (c & 0xFFFFFFFF) + self._fold(l[2], k), k) if self._addr(c & 0xFFFFFFFF) else None
        return None

    @staticmethod
    def _stride(v, s, k):
        """Stride of pointer v (stride s) plus an index * k. Different strides: an array inside an array element
        (objects + 0x38*i + 0x28 + 4*j); a RAM path keeps the gcd as its key, a ROM table needs one stride."""
        if not s or s == k:
            return k
        if not k:
            return s
        if s < 0 or k < 0:
            return -1
        return math.gcd(s, k) if v[0] == "ld" and root(v[1])[0] == "g" and TableFlow._gcd else -1

    @staticmethod
    def _fold(off, k):
        """A negative offset with an index (4*i - 4) addresses the entries from the start: offset mod stride."""
        return off % k if off < 0 and k > 0 else off

    def _add(self, a, b):
        if a and a[0] == "c" and a[1] is not None:
            a, b = b, a
        if b and b[0] == "c" and b[1] is not None:
            return self._addc(a, b[1])
        if a is None or b is None:
            x = a or b
            return (x[0], x[1], -1, None) if x and x[0] in ("ld", "par") else None
        la, lb = self._lin(a), self._lin(b)
        if la and lb and la[0] == lb[0]:
            return ("lin", la[0], la[1] + lb[1], la[2] + lb[2])     # r0 + r0 * 4: an integer
        for x, y in ((a, b), (b, a)):
            if x[0] in ("ld", "par") and y[0] in ("lin", "var"):
                s, o = self._ext(x)
                l = self._lin(y)
                k = l[1] if y[0] == "lin" else 0             # var: unknown byte offset
                if k <= 0 or s < 0 or o is None:
                    return (x[0], x[1], -1, o)
                st = self._stride(x, s, k)
                return (x[0], x[1], st, self._fold(o + l[2], st) if st >= 0 else None)
            if x[0] == "idx" and y[0] in ("lin", "var"):
                l = self._lin(y)
                k = l[1] if y[0] == "lin" else 0
                return ("idx", x[1] + self._fold(l[2], k), x[2] if k == x[2] else 0)
        return None

    def _sub(self, a, b):
        if b and b[0] == "c" and b[1] is not None:
            return self._addc(a, (-b[1]) & 0xFFFFFFFF)
        la, lb = self._lin(a), self._lin(b)
        if la and lb and la[0] == lb[0]:
            return ("lin", la[0], la[1] - lb[1], la[2] - lb[2])
        if a and a[0] in ("ld", "par"):
            return (a[0], a[1], -1, None)
        return None

    def _scale(self, a, k):
        if a is None or k is None:
            return None
        if a[0] == "c":
            return ("c", (a[1] * k) & 0xFFFFFFFF) if a[1] is not None else None
        l = self._lin(a)
        return ("lin", l[0], l[1] * k, l[2] * k) if l else None

    def _loc(self, v):
        """Source of the word a value points at."""
        if not v:
            return None
        if v[0] == "c" and v[1] is not None:
            if self.is_rom(v[1]):
                return ("at", v[1] - ROM)
            return ("g", v[1], 0, 0) if is_ram(v[1]) else None
        if v[0] == "idx" and v[2] > 0:
            if self.is_rom(v[1]):
                return ("fld", v[1] - ROM, v[2], 0)
            return ("g", v[1], v[2], 0) if is_ram(v[1]) else None
        if v[0] in ("ld", "par") and v[1] is not None:
            s, o = self._ext(v)
            if o is None or s < 0:
                return None
            return ("sub", v[1], s, o) if v[0] == "ld" else ("parf", v[1], s, o)
        return None

    def _at(self, v, s, off):
        """Source of the word at value v + i*s + off."""
        if not v or off is None:
            return None
        if s and v[0] == "idx" and v[2] and v[2] != s:
            return None
        w = self._addc(v, off)
        if w and s:
            if w[0] in ("c", "idx"):
                w = ("idx", w[1], s)
            elif w[0] in ("ld", "par"):
                w = (w[0], w[1], self._stride(w, w[2], s), w[3])
            else:
                w = None
        return self._loc(w)

    def _source(self, base, idx, disp, has_idx):
        addr = self._add(base, idx) if has_idx else base
        if not has_idx and base and base[0] == "idx" and not base[2]:
            return None
        return self._loc(self._addc(addr, disp) if disp else addr)

    # ------------------------------------------------------------------ evidence
    def mark_ptr(self, val, why):
        if val and val[0] == "ld":
            src = val[1]
            if src:
                r = root(src)[0]
                if r == "parf":
                    if self._func is not None:
                        self.psum[self._func].add((src, "ptr"))
                elif r == "g":
                    if self._rec:
                        self.ram_ev[src].add("ptr")
                elif self._rec:
                    self.ev_ptr[src].add(why)
            return True
        return False

    def _data(self, src, why):
        r = root(src)[0]
        if r == "parf":
            if self._func is not None:
                self.psum[self._func].add((src, "data"))
        elif r == "g":
            if self._rec and src[0] == "sub":
                self.ram_ev[src].add("data")
        elif self._rec:
            self.ev_data[src].add(why)

    @staticmethod
    def _depends(v):
        return v is not None and (v[0] == "par" or (v[0] in ("ld", "sub", "parf") and v[1] is not None
                                                      and root(v[1] if v[0] == "ld" else v)[0] == "parf"))

    def _storable(self, v):
        if not v:
            return False
        if v[0] in ("c", "idx"):
            return self._addr(v[1]) and (v[0] == "c" or v[2] > 0)
        return v[0] in ("ld", "par") and v[1] is not None

    def _store(self, loc, v, func):
        if not loc or not self._storable(v):
            return
        v = v[:2] if v[0] == "c" else v[:3] if v[0] == "idx" else v
        if self._depends(loc) or self._depends(v):
            if func is not None:
                self.psum[func].add((loc, ("store", v)))
        elif root(loc)[0] == "g" and self._rec:
            self.stores[loc].add(v)

    def _inst(self, path, pre):
        """Path rooted at a callee argument -> source in the caller (pre = registers at the call)."""
        if path[0] == "parf":
            return self._at(pre.get(f"r{path[1]}"), path[2], path[3])
        if path[0] == "sub":
            inner = self._inst(path[1], pre)
            return ("sub", inner, path[2], path[3]) if inner and depth(inner) < 6 else None
        return path

    def _instv(self, v, pre):
        if v[0] == "par":
            s, o = self._ext(v)
            return self._addc(pre.get(f"r{v[1]}"), o) if s == 0 and o is not None else None
        if v[0] == "ld" and root(v[1])[0] == "parf":
            src = self._inst(v[1], pre)
            return ("ld", src) + tuple(v[2:]) if src else None
        return v

    def _resolve(self):
        """RAM links: evidence on a RAM path applies to the values stored at that path (or at a prefix of it)."""
        work = [(e, k) for e, ks in self.ram_ev.items() for k in ks]
        seen = set()
        self._rec = True
        while work:
            e, kind = work.pop()
            if (e, kind) in seen:
                continue
            seen.add((e, kind))
            levels = [e]
            while levels[-1][0] == "sub":
                levels.append(levels[-1][1])
            for j, P in enumerate(levels):
                for v in self.stores.get(P, ()):
                    why = ("ram", repr(P))
                    if j == 0:
                        if kind == "ptr" and v[0] == "ld":
                            r = root(v[1])[0]
                            if r == "g":
                                work.append((v[1], "ptr"))
                            elif r in ("at", "fld"):
                                self.ev_ptr[v[1]].add(why)
                        continue
                    new = self._at(v, levels[j - 1][2], levels[j - 1][3])
                    for k in range(j - 2, -1, -1):
                        new = ("sub", new, levels[k][2], levels[k][3]) if new and depth(new) < 8 else None
                    if not new:
                        continue
                    r = root(new)[0]
                    if r == "g":
                        work.append((new, kind))
                    elif r in ("at", "fld"):
                        (self.ev_ptr if kind == "ptr" else self.ev_data)[new].add(why)

    # ------------------------------------------------------------------ interpretation
    def _step(self, ins, regs, func, record=True):
        self._func, self._rec = func, record
        if record and ins.address - ROM in self.trace:
            self.trace[ins.address - ROM] = dict(regs)
        m, ops = ins.mnemonic, ins.operands
        name = lambda op: self.md.reg_name(op.reg)
        sp = regs.get("sp")
        d = sp[1] if sp and sp[0] == "sp" else None
        prev_pop = getattr(self, "_popped", ())
        self._popped = ()
        # ---- stack
        if m in ("push", "pop"):
            rl = [name(op) for op in ops if op.type == ARM_OP_REG]
            if d is None:
                for r in rl:
                    if m == "pop" and r != "pc":
                        regs[r] = ("var", ins.address, r)
                return
            if m == "push":
                d -= 4 * len(rl)
                for j, r in enumerate(rl):
                    v = regs.get(r)
                    regs[f"stk{d + 4 * j}"] = v if v is not None else ("var", ins.address, r)
            else:
                for j, r in enumerate(rl):
                    if r != "pc":
                        v = regs.get(f"stk{d + 4 * j}")
                        regs[r] = v if v is not None else ("var", ins.address, r)
                d += 4 * len(rl)
                self._popped = tuple(rl)
                if "pc" in rl:
                    self._ret(regs, func)
            regs["sp"] = ("sp", d)
            return
        dst = name(ops[0]) if ops and ops[0].type == ARM_OP_REG else None
        if dst == "sp":
            if m in ("add", "sub") and len(ops) == 2 and ops[1].type == ARM_OP_IMM and d is not None:
                regs["sp"] = ("sp", d + (ops[1].imm if m == "add" else -ops[1].imm))
            else:
                regs["sp"] = None
            return
        if m in ("add", "adds") and len(ops) == 3 and ops[1].type == ARM_OP_REG and name(ops[1]) == "sp" \
                and ops[2].type == ARM_OP_IMM:
            regs[dst] = ("spa", d + ops[2].imm) if d is not None else ("var", ins.address, dst)
            return
        if m in ("mov", "movs") and len(ops) == 2 and ops[1].type == ARM_OP_REG and name(ops[1]) == "sp":
            regs[dst] = ("spa", d) if d is not None else ("var", ins.address, dst)
            return
        if m == "adr" and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
            regs[dst] = ("c", ((ins.address + 4) & ~3) + ops[1].imm)
            return
        if m in LOADS + ("str", "strh", "strb") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            bn = self.md.reg_name(mem.base)
            bv = regs.get(bn)
            slot = None
            if bn == "sp" and not mem.index and d is not None:
                slot = d + mem.disp
            elif bv and bv[0] == "spa" and not mem.index:
                slot = bv[1] + mem.disp
            elif (bv and bv[0] == "spa") or bn == "sp":
                self._clear_stack(regs)
                if m in LOADS:
                    regs[dst] = ("var", ins.address, dst)
                return
            if slot is not None:
                if m == "ldr":
                    v = regs.get(f"stk{slot}")
                    regs[dst] = v if v is not None else ("var", ins.address, dst)
                elif m in LOADS:
                    regs[dst] = ("var", ins.address, dst)
                elif m == "str":
                    v = regs.get(dst)
                    regs[f"stk{slot}"] = v if v is not None else ("var", ins.address, dst)
                else:
                    regs.pop(f"stk{slot & ~3}", None)
                return
        # ---- loads (own version: nested, RAM and argument sources)
        if m in LOADS and len(ops) == 2 and ops[1].type == ARM_OP_MEM and self.md.reg_name(ops[1].mem.base) != "pc":
            base, idx, disp, has_idx = self._base(regs, ops[1].mem)
            self.use_lit(base, "addr"); self.use_lit(idx, "addr")
            width = 4 if m == "ldr" else 2 if m in ("ldrh", "ldrsh") else 1
            src = self._source(base, idx, disp, has_idx)
            self._deref(base, idx, func, ins)
            if src and width < 4:
                self._data(src, ("narrow", width, ins.address))
            regs[dst] = ("ld", src, 0, 0) if (src and width == 4) else ("var", ins.address, dst)
            return
        if m in ("ldm", "ldmia") and ops and ops[0].type == ARM_OP_REG:
            bn = name(ops[0])
            base = regs.get(bn)
            rl = [name(op) for op in ops[1:] if op.type == ARM_OP_REG]
            self._deref(base, None, func, ins)
            for j, r in enumerate(rl):
                src = self._source(base, None, 4 * j, False) if base else None
                regs[r] = ("ld", src, 0, 0) if src else ("var", ins.address, r)
            if "!" in ins.op_str and bn not in rl:
                regs[bn] = self._addc(base, 4 * len(rl)) if base else ("var", ins.address, bn)
            return
        # ---- stores to RAM: remember ROM values (and RAM addresses) per access path
        if m == "str" and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            base, idx, disp, has_idx = self._base(regs, ops[1].mem)
            self._store(self._source(base, idx, disp, has_idx), regs.get(dst), func)
        # ---- calls: return values and summaries
        if m == "bl" and ops and ops[0].type == ARM_OP_IMM:
            pre = dict(regs)
            if any((pre.get(f"r{k}") or ("",))[0] == "spa" for k in range(4)):
                self._clear_stack(regs)
            super()._step(ins, regs, func, record)
            t = self.resolve(ops[0].imm - self.base)
            for path, kind in self.psum.get(t, ()):
                src = self._inst(path, pre)
                if not src:
                    continue
                if kind == "ptr":
                    self.mark_ptr(("ld", src), ("sum", t, ins.address))
                elif kind == "data":
                    self._data(src, ("sum", t, ins.address))
                else:
                    v = self._instv(kind[1], pre)
                    if v:
                        self._store(src, v, func)
            r = self.ret.get(t)
            if r and r is not CONFLICT:
                regs["r0"] = self._instv(r, pre) if r[0] == "par" else r
                if regs["r0"] is None:
                    regs["r0"] = ("var", ins.address, "r0")
            return
        if m == "svc":
            if any((regs.get(f"r{k}") or ("",))[0] == "spa" for k in range(4)):
                self._clear_stack(regs)
        if m == "bx":
            r = name(ops[0]) if ops else None
            if r == "lr" or r in prev_pop:
                self._ret(regs, func)
                return
        if m in ("stm", "stmia") and ops and ops[0].type == ARM_OP_REG:
            bn = name(ops[0])
            base = regs.get(bn)
            if (base or ("",))[0] == "spa":
                self._clear_stack(regs)
            elif base and not (base[0] == "c" and base[1] in typeflow.IO_DMA):
                rl = [name(op) for op in ops[1:] if op.type == ARM_OP_REG]
                for j, r in enumerate(rl):
                    self._store(self._source(base, None, 4 * j, False), regs.get(r), func)
                super()._step(ins, regs, func, record)
                if "!" in ins.op_str and bn not in rl:
                    regs[bn] = self._addc(base, 4 * len(rl)) or ("var", ins.address, bn)
                return
        super()._step(ins, regs, func, record)

    @staticmethod
    def _clear_stack(regs):
        for k in [k for k in regs if k.startswith("stk")]:
            del regs[k]

    def _ret(self, regs, func):
        if func is None or not self._rec:
            return
        v = regs.get("r0")
        if v and v[0] == "c" and self._addr(v[1]):
            v = v[:2]
        elif v and v[0] == "idx" and self._addr(v[1]) and v[2] > 0:
            v = v[:3]
        elif not (v and ((v[0] == "ld" and v[1] is not None and root(v[1])[0] != "parf") or v[0] == "par")):
            v = CONFLICT
        self._retv[func].add(v)

    # ------------------------------------------------------------------ results
    def words(self, bounds=()):
        """Like typeflow.words(); tables are spread with bounds = labels + MFT files + `bounds` (targets of pointers
        known otherwise) + the targets of every pointer found in a first round (two rounds)."""
        base = set(self.labels()) | set(self.g.entries) | set(bounds)
        self.bounds = sorted(base)
        p, dd = super().words()
        tg = {(self.rom_u32(a) & ~1) - ROM for a in p if self.is_rom(self.rom_u32(a))}
        self.bounds = sorted(base | tg)
        self.inconsistent = {}
        p, dd = super().words()
        self.walked = {}                              # byte/halfword streams behind a walked pointer: candidates
        self._walk = True
        for src, why in self.ev_data.items():
            if src[0] == "sub" and src[2] > 0:
                for a in self._spread(src, want_ptr=False):
                    self.walked.setdefault(a, (src, sorted(why)[0]))
        self._walk = False
        return p, dd

    def _spread(self, src, want_ptr):
        if src[0] in ("parf", "g"):
            return []
        if src[0] == "fld" and src[2] and self.bounds:
            return self._table(src[1], src[2], src[3], want_ptr)
        if src[0] != "sub":
            return super()._spread(src, want_ptr)
        _, parent, s, off = src
        r = root(src)
        mft = self.g.mft_off
        if r[0] not in ("at", "fld") or mft <= r[1] < mft + 4 * len(self.g.entries):
            return []                                 # MFT files have different formats: no common layout
        out, bad = [], 0
        for p in self._spread(parent, True):
            w = self.rom_u32(p)
            if not self.is_rom(w):
                continue
            T = w - ROM
            if want_ptr and 0 <= T + off <= self.rom_size - 4:
                v = self.rom_u32((T + off) & ~3)
                if (T + off) % 4 or not (v == 0 or self.is_rom(v)):
                    bad += 1                          # this instance does not hold a pointer there
                    continue
            if not s:
                a = T + off
                if 0 <= a <= self.rom_size - 4:
                    out.append(a & ~3)
                continue
            if not want_ptr and not self._walk:       # data read through a walked pointer: extent unknown
                continue
            out += self._table(T, s, off, want_ptr)
        if bad:
            self.inconsistent[src] = bad              # objects of different layouts behind one field: no proof
            return []
        return out

    def _table(self, T, s, off, want_ptr):
        """Entries T + i*s + off up to the next boundary after T (never over code; pointer fields: while the
        entries are pointer-like or 0)."""
        k = bisect.bisect_right(self.bounds, T)
        limit = self.bounds[k] if k < len(self.bounds) else self.rom_size
        out = []
        for i in range(4096):
            e = T + i * s
            a = e + off
            if e >= limit or a > self.rom_size - 4 or a < 0 or (want_ptr and a % 4):
                break
            a &= ~3
            if a in self.rom_code or a + 2 in self.rom_code:
                break
            v = self.rom_u32(a)
            if want_ptr and not (v == 0 or self.is_rom(v)):
                break
            out.append(a)
        return out


if __name__ == "__main__":
    import time
    t = time.time()
    f = TableFlow(sys.argv[1]).run()
    p, dta = f.words()
    pl = lambda a: ROM <= struct.unpack_from("<I", f.d, a)[0] < ROM + len(f.d)
    print(f"{time.time() - t:.0f}s; functions with return values:",
          sum(1 for v in f.ret.values() if v is not CONFLICT), "summaries:", sum(len(v) for v in f.psum.values()),
          "RAM paths with stores:", len(f.stores), "with evidence:", len(f.ram_ev))
    print("pointer evidence (pointer-like words):", sum(1 for a in p if pl(a)))
    print("data evidence (pointer-like words):", sum(1 for a in dta if pl(a)))
    print("both:", sum(1 for a in p if a in dta and pl(a)))
