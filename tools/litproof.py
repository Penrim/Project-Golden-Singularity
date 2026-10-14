"""How GS1's engine uses each literal-pool constant whose value looks like a ROM address (static, no emulator).

typeflow.Flow records literal uses on one merged state per block, so a value is missed when it reaches its use
through a branch join, a return value, a callee, ldm/stm, a stack slot or a RAM variable. This module follows ONE
literal at a time along every path (taint) and records what happens to it:
  addr      base/index of a load/store/ldm/stm, also inside callees (recursively) and the IWRAM routines
            (typeflow.IWRAM_DEREF); BIOS copy/decompress source; DMA source; bx/mov pc (jump)
  size      end - start with another literal (both must move together)
  ret       returned in r0 (getter): followed into every caller after the bl
  stored    written to RAM: a global (RAM literal + offset), a field of an object, a stack slot (followed)
  cmp       compared with an immediate or a register
  arith     shifted, multiplied ... (number use); fill-value = the word an IWRAM fill routine writes (data)
Stored values are followed through RAM: every 32-bit load of the same location (same global, or same field of the
object held in the same global) is traced in turn; if such a load is used as an address, the field is pointer-typed.
Locations are tracked symbolically: ("G", a) = global, ("@", d, k) = the word at d + k (an object pointer),
("P", j) = argument j (resolved through all callers, also indirect calls through ROM function tables), returned
objects (e.g. pool elements) via return-value summaries, and pointer globals that always hold the same address.
Paths through loops are followed once ("first path wins"): a pool search returns the pool's first element, which
has the type of every element.
Calls through ARM code (IWRAM routines, routines copied to RAM by DMA) use a short ARM scan of the arguments the
routine reads through; the IRQ handler's vector table (literal pool of the IWRAM image, ldr ip,[pc]; bx ip) makes
handlers installed there jump targets.

  python litproof.py GS1.gba [probe.txt] [--list]   (prints the categories, typeflow -> litproof, odd values)
"""
import collections, os, struct, sys
sys.setrecursionlimit(20000)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG
import typeflow

ROM = 0x08000000
ADDR = {"addr", "jump", "swi", "dma", "iwram", "arg-deref", "arm-deref", "irq-table"}
# IWRAM routine 0x03000168 (ROM 0x080008D8, ARM): fill r1 bytes at r0 with the word r2 (stm r0!, {r2 x 8})
IWRAM_FILL = {0x03000168: (0, 2)}


def is_ram(v):
    return v is not None and (0x02000000 <= v < 0x02040000 or 0x03000000 <= v < 0x03008000)


class Tracer:
    """Per-literal forward taint over the confirmed engine code of a typeflow.Flow (after run())."""
    MAX_DEPTH, MAX_STEPS = 4, 120000

    def __init__(self, flow):
        self.f = flow
        self.md = flow.md
        self.blocks, self.succ = flow._cfg
        self.where = {o: (b, i) for b, os_ in self.blocks.items() for i, o in enumerate(os_)}
        self.callers = collections.defaultdict(list)   # function entry -> bl sites (offsets)
        for o, ins in flow.insns.items():
            if ins.mnemonic == "bl" and ins.operands and ins.operands[0].type == ARM_OP_IMM:
                t = ins.operands[0].imm - flow.base
                self.callers[flow.resolve(t)].append(o)
                if flow.resolve(t) != t:
                    self.callers[t].append(o)
        self.lit_sites = collections.defaultdict(list)  # literal offset -> (load offset, register)
        for o, ins in flow.insns.items():
            if ins.mnemonic == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == ARM_OP_MEM \
                    and self.md.reg_name(ins.operands[1].mem.base) == "pc":
                la = ((ins.address + 4) & ~3) + ins.operands[1].mem.disp - flow.base
                self.lit_sites[la].append((o, self.md.reg_name(ins.operands[0].reg)))
        self.fcache = {}
        self._loads = None
        has_pred = {t for s_ in self.succ.values() for t in s_}
        self.heads = {b for b in self.blocks if b in flow.entries or b not in has_pred}

    # ------------------------------------------------------------------ helpers
    def iwram_rom(self, addr):
        """ROM offset of an IWRAM address inside the start-up copy (ROM image -> 0x03000000), else None."""
        if not hasattr(self, "_iw"):
            import profiles
            try:
                im = profiles._iwram_image(self.f.d)
                self._iw = (im["iwram_src"] - ROM, im["iwram_bytes"])
            except Exception:
                self._iw = None
        if self._iw and 0x03000000 <= addr < 0x03000000 + self._iw[1]:
            return self._iw[0] + addr - 0x03000000
        return None

    def irq_tables(self):
        """IWRAM addresses of word tables the ARM IRQ handler (first routine of the IWRAM image) loads with
        ldr ip, [pc, #] and then jumps to (bx ip): {table start}. A store with an index into such a table
        installs a handler that the IRQ handler calls."""
        if hasattr(self, "_irq"):
            return self._irq
        self._irq = set()
        if self.iwram_rom(0x03000000) is None:
            return self._irq
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        md.detail = True
        base = self.iwram_rom(0x03000000)
        slots, jumps = set(), False
        for ins in md.disasm(self.f.d[base:base + 0x100], ROM + base):
            if ins.mnemonic.startswith("ldr") and ins.op_str.startswith("ip, [pc"):
                slots.add(ins.address + 8 + ins.operands[1].mem.disp - ROM - base + 0x03000000)
            if ins.mnemonic == "bx" and ins.op_str == "ip":
                jumps = True
                break
        if jumps and slots:
            self._irq = {min(slots)}
            self._irq_range = (min(slots), max(slots) + 4)
        return self._irq

    def irq_slot(self, loc):
        """loc = (descriptor, offset) is a slot of the IRQ vector table."""
        self.irq_tables()
        r = getattr(self, "_irq_range", None)
        return bool(r and loc[0] and loc[0][0] == "G" and r[0] <= loc[0][1] + loc[1] < r[1])

    def arm_deref(self, a, limit=48):
        """Arguments r0-r3 an ARM routine at ROM offset a reads through (load/store/ldm base) before it
        overwrites them; straight-line scan up to the first branch or return."""
        key = ("arm", a)
        if key in self.fcache:
            return self.fcache[key]
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        md.detail = True
        live, out = {"r0", "r1", "r2", "r3"}, set()
        pc, n, seen = a, 0, set()
        while n < limit and pc not in seen:
            seen.add(pc)
            ins = next(md.disasm(self.f.d[pc:pc + 4], ROM + pc), None)
            if ins is None:
                break
            n += 1
            pc += 4
            ops = ins.operands
            m = ins.mnemonic
            if m == "b" and ops and ops[0].type == ARM_OP_IMM:
                pc = ops[0].imm - ROM                 # unconditional branch: follow
                continue
            if m.startswith(("ldr", "str")) and len(ops) >= 2 and ops[1].type == ARM_OP_MEM:
                b = md.reg_name(ops[1].mem.base)
                if b in live:
                    out.add(int(b[1]))
            if m.startswith(("ldm", "stm", "pop", "push")) and ops and ops[0].type == ARM_OP_REG:
                b = md.reg_name(ops[0].reg)
                if m.startswith(("ldm", "stm")) and b in live:
                    out.add(int(b[1]))
            if m in ("bx", "blx") or (m == "pop" and "pc" in ins.op_str) or ins.op_str.startswith("pc,") \
                    or (m.startswith("ldm") and "pc" in ins.op_str) or m == "bl":
                break
            if m.startswith(("ldm", "pop")):
                live -= {md.reg_name(x.reg) for x in ops[1 if m.startswith("ldm") else 0:] if x.type == ARM_OP_REG}
            elif ops and ops[0].type == ARM_OP_REG and not m.startswith(("str", "stm", "push", "cmp", "cmn", "tst", "teq")):
                live.discard(md.reg_name(ops[0].reg))
        self.fcache[key] = out
        return out

    def lit(self, la):
        return ("L", la, self.f.u32(la))

    @staticmethod
    def tainted(t):
        return isinstance(t, tuple) and t[0] == "T"

    @staticmethod
    def norm(t):
        """Location descriptor of a base tag (for matching stores with loads); None = not describable."""
        if t is None:
            return None
        if t[0] == "L":
            return ("G", t[2]) if is_ram(t[2]) else None
        if t[0] == "M":
            b = Tracer.norm(t[1])
            return ("@", b, t[2]) if b else None
        if t[0] == "P":
            return t
        return None

    @staticmethod
    def root(x):
        while x is not None and x[0] == "@":
            x = x[1]
        return x

    def lift(self, t, argmap):
        """Translate a callee tag (with ("P", k)) into the caller's context."""
        if t is None:
            return None
        if t[0] == "P":
            return argmap.get(t[1])
        if t[0] == "M":
            b = self.lift(t[1], argmap)
            return ("M", b, t[2]) if b is not None else None
        return t

    # ------------------------------------------------------------------ the walk
    def walk(self, starts, ev, depth, ctx):
        """starts: [(block, index, state)]; ev: list to append events (kind, detail, insn offset).
        Returns the set of return tags of r0 seen at function returns (for getters/pass-through)."""
        rets = set()
        work = collections.deque(starts)             # breadth first: near uses before far ones
        seen = set()
        steps = 0
        while work:
            b, i, st = work.popleft()
            key = (b, i, st.get("#pre"), tuple(sorted(repr((k, v)) for k, v in st.items() if self.tainted(v))))
            if key in seen:
                continue
            seen.add(key)
            os_ = self.blocks[b]
            stop = False
            for o in os_[i:]:
                steps += 1
                if steps > self.MAX_STEPS:
                    ev.append(("budget", None, o))
                    return rets
                r = self.step(o, st, ev, depth, ctx)
                if r == "ret":
                    rets.add(st.get("r0") if self.tainted(st.get("r0")) else None)
                    stop = True
                    break
                if r == "stop":
                    stop = True
                    break
                if not st.get("#pre") and not any(self.tainted(v) for v in st.values()):
                    stop = True
                    break
            if not stop:
                for t in self.succ[b]:
                    work.append((t, 0, dict(st)))
        return rets

    def mem_tag(self, st, mem):
        base = self.md.reg_name(mem.base)
        if base == "sp":
            return ("SP", st.get("#sp", 0)), None
        bt = st.get(base)
        it = st.get(self.md.reg_name(mem.index)) if mem.index else None
        return bt, it

    def step(self, o, st, ev, depth, ctx):
        ins = self.f.insns[o]
        m, ops = ins.mnemonic, ins.operands
        R = lambda op: self.md.reg_name(op.reg)
        T = self.tainted
        dst = R(ops[0]) if ops and ops[0].type == ARM_OP_REG else None
        # ---- loads
        if m in ("ldr", "ldrh", "ldrb", "ldrsh", "ldrsb") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            if self.md.reg_name(mem.base) == "pc":
                la = ((ins.address + 4) & ~3) + mem.disp - self.f.base
                st[dst] = ("T", 0) if la == ctx.get("lit") else self.lit(la)
                if la == ctx.get("lit"):
                    st["#pre"] = False
                return
            bt, it = self.mem_tag(st, mem)
            if T(bt) or T(it):
                ev.append(("addr", (m, mem.disp), o))
            if bt and bt[0] == "SP" and not mem.index:
                st[dst] = st.get(("slot", bt[1] + mem.disp)) if m == "ldr" else None
                return
            if m == "ldr" and bt and bt[0] == "Lidx":
                st[dst] = ("TBL", bt[2] + mem.disp)
            elif m == "ldr" and mem.index and bt and bt[0] == "L" and self.f.is_rom(bt[2]):
                st[dst] = ("TBL", bt[2] + mem.disp)
            elif m == "ldr" and not mem.index and bt is not None and not T(bt):
                st[dst] = ("M", bt, mem.disp)
            else:
                st[dst] = None
            if ctx.get("watch") is not None and o in ctx["watch"]:
                st[dst] = ("T", 0)
                st["#pre"] = False
            return
        # ---- stores
        if m in ("str", "strh", "strb") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            bt, it = self.mem_tag(st, mem)
            v = st.get(dst)
            if T(bt) or T(it):
                ev.append(("addr", (m, mem.disp), o))
            if bt and bt[0] == "SP" and not mem.index:
                st[("slot", bt[1] + mem.disp)] = v if m == "str" else None
                return
            if T(v):
                if bt and bt[0] == "L" and bt[2] is not None and bt[2] + mem.disp in typeflow.IO_DMA and m == "str":
                    ev.append(("dma", None, o))
                elif m != "str":
                    ev.append(("stored-narrow", (m, self.norm(bt), mem.disp), o))
                elif mem.index:
                    ev.append(("stored", ("idx", self.norm(bt), mem.disp), o))
                    if bt and bt[0] == "L" and bt[2] in self.irq_tables():
                        ev.append(("irq-table", bt[2], o))
                else:
                    ev.append(("stored", (self.norm(bt), mem.disp, v[1], ctx.get("func"),
                                          (ctx.get("func"), self.norm(bt))), o))
            return
        if m in ("ldm", "ldmia", "stm", "stmia") and ops and ops[0].type == ARM_OP_REG:
            bt = st.get(R(ops[0])) if R(ops[0]) != "sp" else ("SP", st.get("#sp", 0))
            regs = [R(op) for op in ops[1:] if op.type == ARM_OP_REG]
            if T(bt):
                ev.append(("addr", (m, 0), o))
            if m.startswith("st") and bt and bt[0] == "L" and bt[2] in typeflow.IO_DMA and len(regs) >= 2:
                src, dst_t = st.get(regs[0]), st.get(regs[1])
                if src and src[0] == "L" and self.f.is_rom(src[2]) and not T(dst_t):
                    if dst_t is not None:
                        st[("#code", repr(dst_t))] = src[2]
                    st["#lastcode"] = src[2]
            if m.startswith("st"):
                for k, r in enumerate(regs):
                    v = st.get(r)
                    if not T(v):
                        continue
                    if bt and bt[0] == "L" and bt[2] in typeflow.IO_DMA and k == 0:
                        ev.append(("dma", None, o))
                    elif bt and bt[0] == "SP":
                        st[("slot", bt[1] + 4 * k)] = v
                    else:
                        ev.append(("stored", (self.norm(bt), 4 * k, v[1], ctx.get("func"),
                                              (ctx.get("func"), self.norm(bt))), o))
            else:
                for k, r in enumerate(regs):
                    st[r] = st.get(("slot", bt[1] + 4 * k)) if bt and bt[0] == "SP" else \
                        (("M", bt, 4 * k) if bt is not None and not T(bt) else None)
            if "!" in ins.op_str:
                b = R(ops[0])
                if bt and bt[0] in ("L", "SP"):
                    st[b] = (bt[0], bt[1] + 4 * len(regs)) if bt[0] == "SP" else ("L", bt[1], bt[2] + 4 * len(regs))
                elif not T(bt):
                    st[b] = None
            return
        if m in ("push", "pop"):
            regs = [R(op) for op in ops if op.type == ARM_OP_REG]
            sp = st.get("#sp", 0)
            if m == "push":
                sp -= 4 * len(regs)
                for k, r in enumerate(regs):
                    st[("slot", sp + 4 * k)] = st.get(r)
            else:
                for k, r in enumerate(regs):
                    st[r] = st.get(("slot", sp + 4 * k))
                    if r != "pc" and k == len(regs) - 1 and st[r] is None:
                        st[r] = ("RET",)
                sp += 4 * len(regs)
                if "pc" in regs:
                    st["#sp"] = sp
                    return "ret"
            st["#sp"] = sp
            return
        # ---- calls
        if m == "bl" and ops and ops[0].type == ARM_OP_IMM:
            return self.call(o, ops[0].imm - self.f.base, st, ev, depth, ctx)
        if m == "svc" and ops:
            n = ops[0].imm
            if T(st.get("r0")):
                ev.append(("swi" if n in typeflow.SWI_SRC else "arith", ("svc", n), o))
            if T(st.get("r1")) and n in typeflow.SWI_SRC:
                ev.append(("swi-dest", n, o))
            for r in ("r0", "r1", "r3"):
                st[r] = None
            return
        if m == "bx":
            v = st.get(R(ops[0]))
            if R(ops[0]) == "lr" or (v and v[0] == "RET"):
                return "ret"
            if T(v):
                ev.append(("jump", None, o))
            return "stop"
        if m == "mov" and dst == "pc":
            if T(st.get(R(ops[1]))):
                ev.append(("jump", None, o))
            return "stop"
        if m.startswith("b") and m not in ("bic", "bics"):
            return
        if dst is None:
            return
        if m in ("cmp", "cmn", "tst"):
            vals = [("K", op.imm) if op.type == ARM_OP_IMM else st.get(R(op)) for op in ops]
            for k, v in enumerate(vals):
                if T(v):
                    other = vals[1 - k] if len(vals) == 2 else None
                    oreg = R(ops[1 - k]) if len(vals) == 2 and ops[1 - k].type == ARM_OP_REG else None
                    ev.append(("cmp", (m, other, oreg), o))
            return
        # ---- arithmetic
        srcs = ops[1:]
        val = lambda op: ("K", op.imm) if op.type == ARM_OP_IMM else \
            (("SP", st.get("#sp", 0)) if R(op) == "sp" else st.get(R(op)))
        out = None
        if dst == "sp":
            if m in ("add", "sub") and srcs and srcs[-1].type == ARM_OP_IMM:
                st["#sp"] = st.get("#sp", 0) + (srcs[-1].imm if m == "add" else -srcs[-1].imm)
            return
        if m in ("mov", "movs") and len(srcs) == 1:
            out = val(srcs[0])
        elif m in ("adds", "add", "subs", "sub") and srcs:
            a = st.get(dst) if len(srcs) == 1 else val(srcs[0])
            b_ = val(srcs[-1])
            if len(srcs) == 2 and srcs[0].type == ARM_OP_REG and R(srcs[0]) == "pc":
                out = None
            elif m.startswith("add"):
                out = self.add(a, b_, o, ev)
            else:
                out = self.sub(a, b_, o, ev)
        elif m in ("eors", "orrs", "bics", "ands"):
            a = st.get(dst) if len(srcs) == 1 else val(srcs[0])
            b_ = val(srcs[-1])
            for x, y in ((a, b_), (b_, a)):
                if T(x):
                    k = y[1] & 0xFFFFFFFF if y and y[0] == "K" else None
                    if (m != "ands" and k in (1, 3)) or (m == "ands" and k in (0xFFFFFFFE, 0xFFFFFFFC)):
                        out = ("T", None)               # thumb bit set/cleared: still the address
                    elif m == "eors" and not (y and y[0] == "K"):
                        ev.append(("cmp", ("eors", y, R(srcs[-1]) if y is b_ else dst), o))   # x ^ y == 0
                    else:
                        ev.append(("arith", m, o))
        elif m in ("rsbs", "negs") and srcs and val(srcs[0]) and val(srcs[0])[0] == "K":
            out = ("K", -val(srcs[0])[1])
        elif m == "mvns" and srcs and val(srcs[0]) and val(srcs[0])[0] == "K":
            out = ("K", ~val(srcs[0])[1])
        elif m in ("lsls",) and len(srcs) == 2 and val(srcs[0]) and val(srcs[0])[0] == "K" and srcs[1].type == ARM_OP_IMM:
            out = ("K", (val(srcs[0])[1] << srcs[1].imm) & 0xFFFFFFFF)
        else:
            for op in srcs:
                if op.type == ARM_OP_REG and T(st.get(R(op))):
                    ev.append(("arith", m, o))
        st[dst] = out

    def add(self, a, b, o, ev):
        T = self.tainted
        if b == ("K", 0) and a is not None:          # adds rD, rS, #0 = mov
            return a
        for x, y in ((a, b), (b, a)):
            if T(x):
                if T(y):
                    ev.append(("arith", "add2", o)); return None
                if y and y[0] == "K" and x[1] is not None:
                    return ("T", x[1] + y[1])
                if y and y[0] == "L":
                    ev.append(("arith", ("add-lit", y[1]), o)); return None
                return ("T", None)                       # plus an index
        for x, y in ((a, b), (b, a)):
            if x and y and x[0] == "K" and y[0] in ("K",):
                return ("K", x[1] + y[1])
            if x and x[0] in ("L",) and y and y[0] == "K":
                return ("L", x[1], x[2] + y[1])
            if x and x[0] == "L" and self.f.is_rom(x[2]) and not (y and y[0] in ("L", "SP", "TBL", "M", "P")):
                return ("Lidx", x[1], x[2])
            if x and x[0] == "SP" and y and y[0] == "K":
                return ("SP", x[1] + y[1])
        return None

    def sub(self, a, b, o, ev):
        T = self.tainted
        if b == ("K", 0) and a is not None:
            return a
        if T(a) and T(b):
            return ("K", 0) if a[1] == b[1] else None
        if T(a):
            if b and b[0] == "K" and a[1] is not None:
                return ("T", a[1] - b[1])
            if b and b[0] == "L":
                ev.append(("size", ("end", b[1]), o)); return None
            ev.append(("arith", "sub", o)); return None
        if T(b):
            if a and a[0] == "L":
                ev.append(("size", ("start", a[1]), o)); return None
            ev.append(("arith", "rsub", o)); return None
        if a and a[0] == "K" and b and b[0] == "K":
            return ("K", a[1] - b[1])
        if a and a[0] == "L" and b and b[0] == "K":
            return ("L", a[1], a[2] - b[1])
        if a and a[0] == "SP" and b and b[0] == "K":
            return ("SP", a[1] - b[1])
        return None

    def call(self, o, t, st, ev, depth, ctx):
        T = self.tainted
        f = self.f
        t = f.resolve(t)
        veneer = f.insns.get(t)
        callee = t
        if veneer is not None and veneer.mnemonic == "bx" and veneer.op_str != "lr":
            v = st.get(veneer.op_str)
            if T(v):
                ev.append(("jump", None, o))
            callee = None
            if v and v[0] == "L" and v[2] in IWRAM_FILL:
                dst_, val_ = IWRAM_FILL[v[2]]
                if T(st.get(f"r{dst_}")):
                    ev.append(("iwram", (v[2], dst_), o))
                if T(st.get(f"r{val_}")):
                    ev.append(("fill-value", (v[2], val_), o))
            arm = None
            if v and v[0] == "L" and v[2] in typeflow.IWRAM_DEREF:
                for k in typeflow.IWRAM_DEREF[v[2]]:
                    if T(st.get(f"r{k}")):
                        ev.append(("iwram", (v[2], k), o))
            elif v and v[0] == "L" and v[2] is not None and v[2] & 1 and f.is_rom(v[2]):
                callee = (v[2] & ~1) - ROM
            elif v and v[0] == "L" and v[2] is not None and not v[2] & 1 and self.iwram_rom(v[2]) is not None:
                arm = self.iwram_rom(v[2])
            elif v is not None and ("#code", repr(v)) in st and not st[("#code", repr(v))] & 1:
                arm = st[("#code", repr(v))] - ROM
            elif (veneer.op_str == "sp" or v is None or v[0] == "RV") and st.get("#lastcode") is not None \
                    and not st["#lastcode"] & 1:
                arm = st["#lastcode"] - ROM            # routine just copied to RAM/stack by DMA, called there
            if arm is not None:
                for k in self.arm_deref(arm):
                    if T(st.get(f"r{k}")):
                        ev.append(("arm-deref", (arm, k), o))
        ret = None
        args = {k: st.get(f"r{k}") for k in range(4)}
        for k in range(4):
            a = args[k]
            if not T(a):
                continue
            if callee is None:
                ev.append(("arg-unknown", k, o))
                continue
            if k in f.deref.get(callee, ()):
                ev.append(("arg-deref", (callee, k), o))
                continue
            if depth >= self.MAX_DEPTH:
                ev.append(("arg-depth", (callee, k), o))
                continue
            sub, rets = self.func_uses(callee, k, depth + 1)
            argmap = {j: args[j] for j in range(4) if j != k}
            for kind, det, at in sub:
                if kind == "stored" and det and det[0] != "idx":
                    det = (self.norm_lift(det[0], argmap),) + det[1:3] + (ctx.get("func"), det[4])
                elif kind in ("stored", "stored-narrow") and det:
                    det = det[:1] + (self.norm_lift(det[1], argmap),) + det[2:]
                ev.append((kind, det, at))
            if any(r is not None for r in rets):
                ret = ("T", None)
            if not sub and not rets:
                ev.append(("arg-unused", (callee, k), o))
        for r in ("r0", "r1", "r2", "r3", "ip", "lr"):
            st[r] = None
        if ret:
            st["r0"] = ret
        elif callee is not None and ctx.get("getter") == callee:
            st["r0"] = ("T", None)
        elif callee is not None:
            rt = self.ret_tag(callee)                 # an object the callee returns (e.g. a pool element)
            if rt is not None:
                st["r0"] = self.lift(rt, args) if not any(self.tainted(a) for a in args.values()) else None
            else:
                st["r0"] = ("RV", o)                  # identity of an unknown return value (e.g. a malloc result)

    def norm_lift(self, d, argmap):
        """Location descriptor from a callee (("@", ("P", j), off) ...) in the caller's context."""
        if d is None:
            return None
        if d[0] == "P":
            return self.norm(argmap.get(d[1]))
        if d[0] == "@":
            b = self.norm_lift(d[1], argmap)
            return ("@", b, d[2]) if b else None
        return d

    def func_uses(self, func, k, depth):
        """Events of argument k inside function func (cached), and its r0 return tags."""
        key = (func, k)
        if key in self.fcache:
            return self.fcache[key]
        self.fcache[key] = ([], set())                # recursion guard
        if func not in self.blocks:
            res = ([("arg-nocode", (func, k), func)], set())
        else:
            st = {f"r{j}": ("P", j) for j in range(4)}
            st[f"r{k}"] = ("T", 0)
            ev = []
            rets = self.walk([(func, 0, st)], ev, depth, {"func": func})
            res = (ev, rets)
        self.fcache[key] = res
        return res

    # ------------------------------------------------------------------ per literal
    def trace_lit(self, la):
        ev = []
        rets = set()
        funcs = {self.function_of(o) for o, _ in self.lit_sites[la]}
        for func in funcs:
            if func is None:
                continue
            st = {f"r{j}": ("P", j) for j in range(4)}
            st["#pre"] = True
            rets |= self.walk([(func, 0, st)], ev, 0, {"lit": la, "func": func})
        for o, reg in self.lit_sites[la]:
            if self.function_of(o) is not None:
                continue
            b, i = self.where[o]
            st = {}
            for p in self.blocks[b][:i]:
                self.step(p, st, [], self.MAX_DEPTH, {})
            for k in list(st):
                if self.tainted(st[k]):
                    st[k] = None
            rets |= self.walk([(b, i, st)], ev, 0, {"lit": la})
        if any(r is not None for r in rets):
            ev.append(("ret", None, None))
            ev += self.trace_return(la)
        return ev

    def function_of(self, o):
        """Head of the function containing offset o: the first head (BL target, stub target, or a block without
        predecessors = a function reached through a pointer, or a switch case) whose blocks reach o."""
        if not hasattr(self, "_owner"):
            own = {}
            for e in sorted(self.heads):
                work = [e]
                while work:
                    b = work.pop()
                    if b in own:
                        continue
                    own[b] = e
                    work += [t for t in self.succ[b] if t not in self.heads]
            self._owner = own
        return self._owner.get(self.where[o][0])

    def trace_return(self, la, depth=0):
        """The literal is returned in r0: follow r0 after every call of the function (getter)."""
        ev = []
        for func in {self.function_of(o) for o, _ in self.lit_sites[la]}:
            if func is None:
                ev.append(("ret-unknown-func", None, None))
                continue
            for site in self.callers.get(func, []):
                b, i = self.where[site]
                st = {}
                for p in self.blocks[b][:i]:
                    self.step(p, st, [], self.MAX_DEPTH, {})
                rets = self.walk([(b, i, st)], ev, 1, {"getter": func, "func": self.function_of(site)})
                if any(r is not None for r in rets):
                    ev.append(("ret2", self.function_of(site), site))
            if not self.callers.get(func):
                ev.append(("ret-no-callers", func, None))
        return ev

    def fstates(self, func):
        """Register tags (arguments seeded as ("P", k)) before every bl of a function (first path wins)."""
        key = ("fst", func)
        if key in self.fcache:
            return self.fcache[key]
        out = {"#ret": []}
        self.fcache[key] = out                        # recursion guard (partial result)
        st0 = {f"r{j}": ("P", j) for j in range(4)}
        work, seen = [(func, st0)], set()
        while work and func in self.blocks:
            b, st = work.pop()
            if b in seen:
                continue
            seen.add(b)
            for o in self.blocks[b]:
                if self.f.insns[o].mnemonic == "bl":
                    out[o] = dict(st)
                r = self.step(o, st, [], self.MAX_DEPTH, {})
                if r == "ret":
                    out["#ret"].append(st.get("r0"))
                if r in ("ret", "stop"):
                    break
            else:
                work += [(t, dict(st)) for t in self.succ[b] if t not in self.heads]
        return out

    def ret_tag(self, func):
        """The object a function returns: the one describable r0 tag of all its returns (0/constants ignored).
        Paths are followed once (first path wins), so a pool search loop returns the pool's first element, which
        has the type of every element."""
        key = ("ret", func)
        if key in self.fcache:
            return self.fcache[key]
        self.fcache[key] = None
        tags = {t for t in self.fstates(func)["#ret"] if not (t and t[0] == "K")}
        good = {t for t in tags if t is not None and self.norm(t) is not None}
        res = good.pop() if len(good) == 1 and len(tags) == 1 else None
        self.fcache[key] = res
        return res

    def callers_of(self, func):
        """Direct (bl) and indirect call sites of a function: bl _call_via_rN with rN loaded from a ROM table
        that holds func's address (the table runs while its words are function heads)."""
        if not hasattr(self, "_icallers"):
            ic = collections.defaultdict(list)
            for h in sorted(self.heads):
                for site, st in self.fstates(h).items():
                    if site == "#ret":
                        continue
                    ins = self.f.insns[site]
                    t = self.f.resolve(ins.operands[0].imm - self.f.base)
                    v = self.f.insns.get(t)
                    if v is None or v.mnemonic != "bx" or v.op_str == "lr":
                        continue
                    tag = st.get(v.op_str)
                    if tag and tag[0] == "TBL":
                        a = tag[1] - ROM
                        while True:
                            w = self.f.u32(a)
                            if not (w and w & 1 and (w - 1 - ROM) in self.heads):
                                break
                            ic[w - 1 - ROM].append(site)
                            a += 4
                    elif tag and tag[0] == "M" and tag[1] and tag[1][0] == "L" and self.f.is_rom(tag[1][2]):
                        w = self.f.u32(tag[1][2] + tag[2] - ROM)
                        if w and w & 1 and (w - 1 - ROM) in self.heads:
                            ic[w - 1 - ROM].append(site)
                    elif tag and tag[0] == "L" and tag[2] and tag[2] & 1 and (tag[2] - 1 - ROM) in self.heads:
                        ic[tag[2] - 1 - ROM].append(site)
            self._icallers = ic
        return self.callers.get(func, []) + self._icallers.get(func, [])

    def field_locations(self, desc, func, disp):
        """Where a location rooted at func's argument can be read back: [(location key)] for every caller
        (global locations, or the caller's own argument-rooted location keyed with the caller)."""
        out = []
        r = self.root(desc)
        if r is None:
            return out
        if r[0] == "G":
            return [(desc, disp)]
        for loc, fn in self.up(desc, func):
            out.append((loc, disp))
        for site in self.callers_of(func):
            caller = self.function_of(site)
            tag = self.fstates(caller).get(site, {}).get(f"r{r[1]}")
            new = self.norm(tag)
            if new is None:
                continue
            d2 = self.subst(desc, new)
            out.append((d2, disp) + ((caller,) if self.root(d2)[0] == "P" else ()))
        return out

    @staticmethod
    def subst(x, new):
        return new if x[0] == "P" else ("@", Tracer.subst(x[1], new), x[2])

    def up(self, desc, func, depth=0):
        """A location rooted at an argument ("P", j) of func, as seen by func's callers: [(location, caller)]."""
        r = self.root(desc)
        subst = self.subst
        if r is None or r[0] == "G":
            return [(desc, func)] if r else []
        if depth > 4 or func is None:
            return []
        out = []
        for site in self.callers_of(func):
            caller = self.function_of(site)
            tag = self.fstates(caller).get(site, {}).get(f"r{r[1]}")
            new = self.norm(tag)
            if new is not None:
                out += self.up(subst(desc, new), caller, depth + 1)
        return out

    def reg_is_address(self, o, reg):
        """Register reg holds an address at instruction o: the same value is a load/store/ldm/stm base in o's block
        (searching back to the instruction that set it, and forward until it is overwritten)."""
        b, i = self.where[o]
        os_ = self.blocks[b]

        def base_of(ins):
            ops = ins.operands
            if ins.mnemonic.startswith(("ldr", "str")) and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
                return self.md.reg_name(ops[1].mem.base)
            if ins.mnemonic.startswith(("ldm", "stm")) and ops and ops[0].type == ARM_OP_REG:
                return self.md.reg_name(ops[0].reg)

        def writes(ins):
            ops = ins.operands
            if ins.mnemonic.startswith(("ldm", "stm", "str", "cmp", "cmn", "tst", "b", "push")) \
                    and ins.mnemonic not in ("bics",):
                return ins.mnemonic.startswith("ldm") and reg in [self.md.reg_name(x.reg) for x in ops[1:]]
            if ins.mnemonic == "pop":
                return reg in [self.md.reg_name(x.reg) for x in ops]
            return bool(ops) and ops[0].type == ARM_OP_REG and self.md.reg_name(ops[0].reg) == reg
        for p in reversed(os_[:i]):
            ins = self.f.insns[p]
            if base_of(ins) == reg:
                return p
            if writes(ins):
                break
        for p in os_[i + 1:]:
            ins = self.f.insns[p]
            if base_of(ins) == reg:
                return p
            if writes(ins):
                break
        return None

    # ------------------------------------------------------------------ RAM locations
    def loads(self):
        """Every 32-bit load with a describable location: descriptor -> [load offsets] (walk per function)."""
        if self._loads is not None:
            return self._loads
        out = collections.defaultdict(list)
        stores = collections.defaultdict(set)
        for e in sorted(self.heads):
            st0 = {f"r{j}": ("P", j) for j in range(4)}
            work, seen = [(e, st0)], set()
            while work:
                b, st = work.pop()
                if b in seen:
                    continue
                seen.add(b)
                for o in self.blocks[b]:
                    ins = self.f.insns[o]
                    if ins.mnemonic == "str" and len(ins.operands) == 2 and ins.operands[1].type == ARM_OP_MEM \
                            and not ins.operands[1].mem.index:
                        bt = st.get(self.md.reg_name(ins.operands[1].mem.base))
                        vt = st.get(self.md.reg_name(ins.operands[0].reg))
                        dsc = self.norm(bt)
                        if dsc and dsc[0] == "G":
                            stores[("@", dsc[0:1] + (dsc[1] + ins.operands[1].mem.disp,), 0)].add(
                                ("G", vt[2]) if vt and vt[0] == "L" and is_ram(vt[2]) else
                                (vt + (e,)) if vt and vt[0] == "P" else None)
                    if ins.mnemonic == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == ARM_OP_MEM \
                            and not ins.operands[1].mem.index and self.md.reg_name(ins.operands[1].mem.base) not in ("pc", "sp"):
                        bt = st.get(self.md.reg_name(ins.operands[1].mem.base))
                        dsc = self.norm(bt)
                        if dsc:
                            key = (dsc, ins.operands[1].mem.disp)
                            out[key + ((e,) if self.root(dsc)[0] == "P" else ())].append(o)
                    if self.step(o, st, [], self.MAX_DEPTH, {}) in ("ret", "stop"):
                        break
                else:
                    for t in self.succ[b]:
                        if t not in self.heads:
                            work.append((t, dict(st)))
        self.alias = {}
        for k, v in stores.items():                   # an argument stored: what every caller passes
            vals = set()
            for x in v:
                if x is not None and x[0] == "P":
                    vals |= {self.norm(self.fstates(self.function_of(c)).get(c, {}).get(f"r{x[1]}"))
                             for c in self.callers_of(x[2])} or {None}
                else:
                    vals.add(x)
            if len(vals) == 1 and None not in vals and next(iter(vals))[0] == "G":
                self.alias[k] = next(iter(vals))
        canon = collections.defaultdict(list)
        for k, v in out.items():
            canon[self.canon_key(k)] += v
        self._loads = canon
        return canon

    def canon(self, d):
        """Descriptor in canonical form: ("@", ("G", g), k) -> ("@", ("G", g + k), 0), and a pointer global
        (one that always holds the address of global X) replaced by ("G", X)."""
        if d is None or d[0] != "@":
            return d
        inner = self.canon(d[1])
        if inner and inner[0] == "G" and d[2]:
            d = ("@", ("G", inner[1] + d[2]), 0)
        else:
            d = ("@", inner, d[2])
        return getattr(self, "alias", {}).get(d, d)

    def canon_key(self, key):
        """Location key (descriptor, offset[, function]) in canonical form."""
        d = self.canon(key[0])
        if d and d[0] == "G" and key[1]:
            return (("G", d[1] + key[1]), 0) + key[2:]
        return (d,) + key[1:]

    def location_use(self, loc):
        """Events of the values loaded from a RAM location (descriptor, offset) anywhere in the engine."""
        self.loads()
        loc = self.canon_key(loc)
        key = ("loc",) + loc
        if key in self.fcache:
            return self.fcache[key]
        self.fcache[key] = ([], set())
        ev = []
        for o in self.loads().get(loc, []):
            b, i = self.where[o]
            st = {}
            for p in self.blocks[b][:i]:
                self.step(p, st, [], self.MAX_DEPTH, {})
            sub = []
            self.walk([(b, i, st)], sub, 1, {"watch": {o}})
            ev += [(k, d, a) for k, d, a in sub]
        self.fcache[key] = (ev, set())
        return self.fcache[key]


NUMBER = {"fill-value", "stored-narrow"}
GOOD = ("address", "function", "address-via-ram", "address-by-identity", "size-of-pointer")


def ram_pointer(tr, loc):
    """A RAM location (descriptor, offset) whose loaded value code uses as an address: the evidence or None."""
    sub, _ = tr.location_use(loc)
    return next((e for e in sub if e[0] in ADDR), None)


def classify(tr, la):
    """(category, evidence list, proof, number evidence) for one literal offset. Categories:
    address / function / address-via-ram / address-by-identity / size (resolved later) / number / number-like /
    unused / unknown"""
    f = tr.f
    w = f.u32(la)
    ev = tr.trace_lit(la)
    kinds = collections.Counter(k for k, _, _ in ev)
    proof = []
    direct = [e for e in ev if e[0] in ADDR]
    if direct:
        proof.append(("address", direct[0]))
    if w & 1 and (w - 1 - ROM) in f.code:
        proof.append(("function", ("code at", (w & ~1) - ROM)))
    for k, det, at in ev:
        if proof:
            break
        if k == "stored" and det and det[0] != "idx":
            locs = []
            if det[0] is not None:
                locs += tr.field_locations(det[0], det[3], det[1])
            org_f, org_d = det[4]
            if org_d is not None and org_f is not None:
                locs += tr.field_locations(org_d, org_f, det[1])
            for loc in dict.fromkeys(locs):
                if tr.irq_slot(loc):
                    proof.append(("address", ("irq-table", loc, at)))
                    break
                e = ram_pointer(tr, loc)
                if e:
                    proof.append(("address-via-ram", (loc, at, e)))
                    break
        elif k == "cmp" and det:
            other, oreg = det[1], det[2]
            dsc = tr.norm(other[1]) if other and other[0] == "M" else None
            if dsc and dsc[0] != "P":
                e = ram_pointer(tr, (dsc, other[2]))
                if e:
                    proof.append(("address-by-identity", ("equals value of", (dsc, other[2]), at, e)))
            if not proof and oreg and at is not None:
                p = tr.reg_is_address(at, oreg)
                if p is not None:
                    proof.append(("address-by-identity", ("equals address register", oreg, at, p)))
    numbers = [e for e in ev if e[0] in NUMBER]
    if proof:
        return proof[0][0], ev, proof[0][1], numbers
    if numbers:
        return "number", ev, numbers[0], numbers
    size = [e for e in ev if e[0] == "size"]
    if size:
        return "size", ev, size[0], numbers
    if kinds.keys() & {"cmp", "arith"} and not kinds.keys() & {"stored", "arg-unknown", "arg-depth"}:
        return "number-like", ev, None, numbers
    if not ev or set(kinds) <= {"arg-unused"}:
        return "unused", ev, None, numbers
    return "unknown", ev, None, numbers


def classify_all(tr):
    """{literal offset: (category, evidence, proof, number evidence)}; size partners resolved."""
    f = tr.f
    rl = sorted(la for la in tr.lit_sites if f.is_rom(f.u32(la)))
    res = {la: classify(tr, la) for la in rl}
    for la, (c, ev, why, nums) in list(res.items()):
        if c == "size":
            partner = why[1][1]
            pc = res.get(partner, ("?",))[0]
            res[la] = ("size-of-pointer" if pc in GOOD else "size", ev, (why, partner, pc), nums)
    return res


def baseline(f, la):
    """typeflow's own literal-use category (lit_use counters), for comparison."""
    u = set(f.lit_use.get(la, {}))
    w = f.u32(la)
    if u & {"addr", "arg-deref", "jump", "swi", "dma"}:
        return "address"
    if w & 1 and (w - 1 - ROM) in f.code:
        return "function"
    if u & {"arg", "stored"}:
        return "passed/stored"
    if u & {"cmp", "arith"}:
        return "number-only"
    return "no-use"


def short(why):
    """One-line evidence text."""
    if why is None:
        return ""
    return repr(why).replace(" ", "")[:160]


def odd_target(tr, w):
    """What an odd value (Thumb address) points at, when the target is not confirmed code:
    bl-target / push-prologue / leaf (straight-line Thumb up to bx lr, bx rN or pop {pc}) / not-code."""
    import reloc
    f = tr.f
    t = w - 1 - ROM
    if t in f.code:
        return "confirmed"
    if not hasattr(tr, "_bls"):
        tr._bls = reloc.bl_targets(f.d, 0, f.end)
    tags = []
    if t in tr._bls:
        tags.append("bl-target")
    if reloc.is_prologue(f.d, t):
        tags.append("push-prologue")
    n = 0
    for ins in f.md.disasm(f.d[t:t + 128], ROM + t):
        n += 1
        if ins.mnemonic == "bx" or (ins.mnemonic == "pop" and "pc" in ins.op_str):
            tags.append(f"leaf:{n}")
            break
        if ins.mnemonic in ("b",) or n > 48:
            tags.append(f"branch:{n}" if ins.mnemonic == "b" else "long")
            break
    else:
        tags.append("invalid")
    first = next(f.md.disasm(f.d[t:t + 4], ROM + t), None)
    return ",".join(tags) + (f" [{first.mnemonic} {first.op_str}]" if first else "")


def report(rom, probe=None):
    """Rows (literal offset, value, typeflow category, litproof category, proof, number evidence, probe)."""
    import wordmap
    f = typeflow.Flow(rom).run()
    tr = Tracer(f)
    res = classify_all(tr)
    pr = wordmap.load_probe(probe) if probe else {}
    rows = []
    for la, (c, ev, why, nums) in sorted(res.items()):
        w = f.u32(la)
        odd = odd_target(tr, w) if w & 1 and (w - 1 - ROM) not in f.code else None
        rows.append((la, w, baseline(f, la), c, why, nums, pr.get(la), ev, odd))
    return rows


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = report(args[0], args[1] if len(args) > 1 else None)
    print("rom-range literals:", len(rows), dict(collections.Counter(r[3] for r in rows)))
    print("typeflow categories:", dict(collections.Counter(r[2] for r in rows)))
    tab = collections.Counter((r[2], r[3]) for r in rows)
    for (b, c), n in sorted(tab.items()):
        print(f"  {b:14s} -> {c:20s} {n:5d}")
    conflicts = [r for r in rows if r[5] and r[3] not in ("number",)]
    print("pointer AND number evidence:", len(conflicts))
    odd = [r for r in rows if r[8]]
    print("odd values whose target is not confirmed code:", len(odd))
    for r in odd:
        print(f"  odd {r[0]:06x} {r[1]:08x} {r[3]:20s} {r[8]}")
    if "--list" in sys.argv:
        for la, w, b, c, why, nums, pe, ev, odd in rows:
            if b not in ("address", "function") or c not in ("address", "function") or nums:
                k = dict(collections.Counter(e[0] for e in ev))
                print(f"{la:06x} {w:08x} {b:14s} {c:20s} probe={pe} {short(why)} {k}")
