"""Evidence for the short runs and single words the GS1 build relocates by heuristics only (tools/wordmap.py
categories guess-plausible and guess-WEAK-isolated): every such word gets a class with its evidence.

Classes (first match wins):
  data:code                 inside Thumb code that is confirmed once switch statements are followed
                            (reloc.strict_code stops at `mov pc, rX`; the case blocks of a jump table bounded by
                            `cmp rI,#N; bhi/bls/bcs/bcc` are code) -> relocating changes an instruction
  pointer:jump-table        follows `ldr r4,[pc,#0]; bx r4` in the export table at the start of an engine code file
                            (format of reloc.stub_targets; map code imports go through these stubs)
  pointer:literal           loaded PC-relative by that code and used as an address (typeflow lit_use)
  pointer:literal-passed    loaded PC-relative by that code, value passed on (argument / stored), use not traced
  data:literal-number       loaded PC-relative, only compared / used in arithmetic
  pointer:arm-literal       loaded by an ARM routine the program runs (cartridge entry, routines confirmed code
                            DMA-copies to RAM, IWRAM image) and used as an address
  data:field / pointer:field  typeflow evidence (RetFlow: + function return values, so get_desc(i)->field is a
                            table field) inside a table of established extent
  pointer:frame-list        sprite frame list: descriptor field stored to object+K, object+K indexed as a word
                            list whose entry is passed (r0) to the frame decoder; lists end with a 0 word
  pointer:anim-list         sprite animation list (the descriptor's other pointer field), entries = scripts
  data:anim-script          bytes the animation interpreter reads (anim_script_bytes; 2-byte commands)
  data:frame-stream         bytes of a compressed frame the decoder reads (GS format 0/1 via gsfs, decoded size =
                            width * height; or the stage-1 streams of decode3), ending exactly at the next frame
  structural:*              in-frame-data (between two frames, stream end not verified), unreached-literal (literal
                            pool of code no confirmed code reaches), loaded-32bit (loaded, use not traced)
  unknown                   none of the above
Probe (recorded all-words tour): narrow reads -> data, wide + used -> pointer are already wordmap categories; wide
reads alone are not proof (a jump-table ldr or a DMA source is read wide without a data read at the target).

  python singles.py GS1.gba [probe.txt] [--usa USA_GS1.gba] [--list CLASS] [--tsv FILE]
      --usa maps the hand-verified words; --tsv appends the contradictions and unproven words (plus the sprite
      evidence's contradictions in other categories) as lang, offset, value, wordmap category, class, evidence
"""
import bisect, collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from gsfs import Rom
import profiles, reloc, typeflow, wordmap

ROM = 0x08000000
CATS = ("guess-plausible", "guess-WEAK-isolated")
THUMB = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def u32(d, a):
    return struct.unpack_from("<I", d, a)[0]


# ---------------------------------------------------------------------------------------------- switch tables --
def switch_tables(d, code, size):
    """Bounded jump tables of confirmed code: `cmp rI,#N; bhi default (or bls table); ... ldr rT,=TABLE;
    lsls rI,#2; ldr rX,[rI,rT]; mov pc,rX`. Returns {table offset: [case offsets]} (N + 1 entries for bhi/bls,
    N for bcs/bcc)."""
    out = {}
    for h in code:
        ins = d[h] | d[h + 1] << 8
        if ins & 0xFF87 != 0x4687:                    # mov pc, rX
            continue
        win = []
        for k in range(1, 12):
            o = h - 2 * k
            if o not in code:
                break
            win.append(next(THUMB.disasm(d[o:o + 2], ROM + o), None))
        win = [i for i in win if i is not None]
        table = count = None
        for i in win:
            if table is None and i.mnemonic == "ldr" and "pc" in i.op_str:
                v = u32(d, ((i.address + 4) & ~3) + int(i.op_str.split("#")[-1].rstrip("]"), 16) - ROM)
                if ROM <= v < ROM + size:
                    table = v - ROM
            if i.mnemonic == "cmp" and "#" in i.op_str and count is None:
                n = int(i.op_str.split("#")[-1], 16)
                nxt = next(THUMB.disasm(d[i.address - ROM + 2:i.address - ROM + 4], i.address + 2), None)
                if nxt is not None and nxt.mnemonic in ("bhi", "bls"):       # unsigned: index <= N
                    count = n + 1
                elif nxt is not None and nxt.mnemonic in ("bhs", "bcs", "blo", "bcc"):   # index < N
                    count = n
                break
        if table is None or not count or table % 4:
            continue
        cases = [u32(d, table + 4 * k) - ROM for k in range(count)]
        if all(0 <= c < size and not c & 1 and abs(c - h) < 0x10000 for c in cases):
            out[table] = cases
    return out


def extended_code(g, end, parts=None):
    """reloc.strict_code from the build's roots plus the case blocks of bounded switch tables (iterated: case blocks
    contain further switches and calls). Returns (code, switch tables)."""
    d = g.data
    if parts is None:
        parts = {}
        reloc.analyse(g, end, parts=parts)
    stubs = reloc.stub_targets(g, end)
    roots = set(stubs)
    tables = {}
    while True:
        code = reloc.strict_code(d, roots, end, parts["roots"] - stubs, parts["runs"] | parts["strided"])
        tables = switch_tables(d, code, end)
        new = {c for cs in tables.values() for c in cs} - roots
        if not new:
            return code, tables
        roots |= new


# ------------------------------------------------------------------------------------------- return values --
class RetFlow(typeflow.Flow):
    """typeflow.Flow with function return values: a function whose every return leaves r0 = table + index * stride
    (or one ROM constant, or one loaded ROM word) gives its callers that value, so `get_desc(i)->field` becomes a
    table field and `p = get_ptr(); *p` makes the loaded word a pointer."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rets = collections.defaultdict(set)
        self.summary = {}
        self.field_loads = collections.defaultdict(set)    # (T, stride, off) -> {(load offset, register)}
        self.wide_loads = collections.defaultdict(set)     # source -> {load offset}: every 32-bit ROM table load

    def run(self, rounds=4):
        for r in range(rounds):
            before = (sum(len(v) for v in self.deref.values()), dict(self.summary))
            self.ev_ptr.clear(); self.ev_data.clear(); self.rets.clear()
            self._pass()
            self.summary = {}
            for f, vs in self.rets.items():
                if len(vs) == 1:
                    v = next(iter(vs))
                    if v and (v[0] == "idx" and v[2] > 0 or v[0] == "c" and self.is_rom(v[1]) or v[0] == "ld" and v[1]):
                        self.summary[f] = v
            if (sum(len(v) for v in self.deref.values()), self.summary) == before and r:
                break
        return self

    def _step(self, ins, regs, func, record=True):
        m = ins.mnemonic
        prev = self.insns.get(ins.address - self.base - 2)
        ret = m == "bx" and (ins.op_str == "lr" or prev is not None and prev.mnemonic == "pop"
                             and ins.op_str in prev.op_str) or m == "pop" and "pc" in ins.op_str
        if func is not None and ret:
            v = regs.get("r0")
            self.rets[func].add(v[:3] if v and v[0] == "idx" else v[:2] if v and v[0] in ("c", "ld") else None)
        r = super()._step(ins, regs, func, record)
        if record and m == "ldr" and ins.operands and ins.operands[0].type == 1:
            v = regs.get(self.md.reg_name(ins.operands[0].reg))
            if v and v[0] == "ld" and v[1] and v[1][0] == "fld":
                self.field_loads[v[1][1:]].add((ins.address - self.base, self.md.reg_name(ins.operands[0].reg)))
            if v and v[0] == "ld" and v[1]:
                self.wide_loads[v[1]].add(ins.address - self.base)
        if m == "bl" and ins.operands and ins.operands[0].type == 2:
            s = self.summary.get(self.resolve(ins.operands[0].imm - self.base))
            if s is not None:
                regs["r0"] = s
        return r


# ---------------------------------------------------------------------------------------------- jump tables --
def stub_chains(g, end):
    """Export tables at the start of the engine code files: {word offset: chain start}. File 0 is the ROM itself,
    its table follows the cartridge header (0xC0)."""
    d, out = g.data, {}
    for e in sorted(set(g.entries)):
        if not 0 <= e < end:
            continue
        o = 0xC0 if e == 0 else e
        s = o
        while d[o:o + 4] == reloc.STUB:
            out[o + 4] = s
            o += 8
    return out


def mapcode_imports(g, gp):
    """ROM addresses named by the import stubs of the map code files (ldr r4,[pc]; bx r4; .word engine stub)."""
    out = collections.Counter()
    for i in range(*gp["mapcode"]):
        b = g.decompressed(i)
        for a in range(4, len(b) - 3, 2):
            if b[a - 4:a] == reloc.STUB:
                w = u32(b, a)
                if ROM <= w < ROM + len(g.data):
                    out[(w & ~1) - ROM] += 1
    return out


# ------------------------------------------------------------------------------------------------ ARM code --
ARM = Cs(CS_ARCH_ARM, CS_MODE_ARM)
ARM.detail = True


def arm_entries(g, gp, flow):
    """ARM routines the program runs: the cartridge entry (header branch), routines confirmed Thumb code DMA-copies
    to RAM (literal used as DMA source), and IWRAM-image routines confirmed code jumps to (via _call_via_rX)."""
    d = g.data
    w0 = u32(d, 0)
    out = {8 + ((w0 & 0xFFFFFF) << 2): "cartridge entry (header branch at 0)"}
    src, n = gp["iwram_src"] - ROM, gp["iwram_bytes"]
    for o, use in flow.lit_use.items():
        v = u32(d, o) if 0 <= o <= len(d) - 4 else None
        if v is None:
            continue
        if use.get("dma") and ROM <= v < ROM + gp["code_end"] and not v & 3 and d[v - ROM + 3] >> 4 == 0xE:
            out.setdefault(v - ROM, f"DMA source loaded at {o:#x}")
        if use.get("jump") and 0x03000000 <= v < 0x03000000 + n and not v & 3:
            out.setdefault(src + v - 0x03000000, f"IWRAM {v:#x} called via literal {o:#x}")
    out.setdefault(src, "IWRAM image start (IRQ handler)")
    return out


def arm_literals(d, entries, end, span=0x1000):
    """Recursive descent over ARM code from the entries (branches followed within `span` bytes of their routine).
    Returns {literal offset: [(loader offset, register, use)]}; use = "address" when the loaded register is next
    used as a memory base or branch target, else "other"."""
    lits = collections.defaultdict(list)
    seen = set()
    for e0 in entries:
        work = [e0]
        while work:
            pc = work.pop()
            while e0 <= pc < min(end, e0 + span) and pc not in seen:
                seen.add(pc)
                ins = next(ARM.disasm(d[pc:pc + 4], ROM + pc), None)
                if ins is None:
                    break
                m, op = ins.mnemonic, ins.op_str
                if m.startswith("ldr") and "[pc" in op and len(ins.operands) == 2:
                    mem = ins.operands[1].mem
                    la = pc + 8 + mem.disp
                    reg = ARM.reg_name(ins.operands[0].reg)
                    lits[la].append((pc, reg, _arm_use(d, pc + 4, reg)))
                if m in ("b", "bl") or (m[:1] == "b" and m not in ("bx", "bic", "bics", "bl") and len(m) <= 3):
                    if ins.operands and ins.operands[0].type == 2:
                        work.append(ins.operands[0].imm - ROM)
                    if m == "b":
                        break
                    pc += 4
                    continue
                if m == "bx" and ins.cc == 15 - 1 or m.startswith("bx") and len(m) == 2:
                    break
                if (m.startswith("pop") or m.startswith("ldm")) and "pc" in op and len(m) in (3, 5, 6) \
                        and not any(m.endswith(c) for c in ("eq", "ne", "hs", "lo", "mi", "pl", "hi", "ls", "ge", "lt",
                                                             "gt", "le")):
                    break
                if m == "mov" and op.startswith("pc"):
                    break
                pc += 4
    return lits


def _arm_use(d, pc, reg, n=12):
    """How the next instructions use a register: "address" (memory base, bx/mov pc) or "other"."""
    for k in range(n):
        ins = next(ARM.disasm(d[pc + 4 * k:pc + 4 * k + 4], ROM + pc + 4 * k), None)
        if ins is None:
            return "other"
        mem = ins.op_str[ins.op_str.find("["):] if "[" in ins.op_str else ""
        if reg in mem.replace("[", " ").replace("]", " ").replace(",", " ").split() \
                or ins.mnemonic.startswith("bx") and ins.op_str == reg:
            return "address"
        if ins.op_str.split(",")[0] == reg:
            return "other"                                # overwritten
    return "other"


def unreached_loader(d, a, code):
    """A Thumb `ldr rX,[pc,#imm]` that loads word a from code that is not confirmed: the loader lies in a function
    that decodes linearly from a push {.., lr} prologue, and a return or branch lies between it and the word.
    Returns (loader, prologue) or None."""
    for h in range(max(0, a - 1020), a, 2):
        if d[h + 1] & 0xF8 != 0x48 or ((h + 4) & ~3) + d[h] * 4 != a or h in code:
            continue
        if not any(d[x + 1] == 0xBD or d[x + 1] == 0x47 and d[x] & 0x87 == 0 or d[x + 1] & 0xF8 == 0xE0
                   or d[x + 1] == 0x46 and d[x] & 0x87 == 0x87 for x in range(h, a, 2)):
            continue                                  # no pop {pc} / bx / b / mov pc before the pool
        p = h
        while p > h - 0x2000 and d[p + 1] != 0xB5:
            p -= 2
        if d[p + 1] != 0xB5:
            continue
        if all(next(THUMB.disasm(d[x:x + 2], ROM + x), None) is not None or d[x + 1] >> 3 in (0x1E, 0x1F)
               for x in range(p, h, 2)):
            return h, p
    return None


# --------------------------------------------------------------------------------------------- sprite data --
def frame_extent_c3(d, src):
    """Sprite frame decoder of compression type 3 (Thumb routine decode3(src, dst), USA 0x0800A97C): u16 h; literal
    bytes from src+2, control stream from src+h: flag byte | 0x100, LSB first, 1 = one literal byte, 0 = big-endian
    u16 c from the control stream: 0 ends, else length (c >> 12, or 0 -> next control byte + 16) + 2 copied from
    src+2 - (c & 0xFFF). Returns (offsets of both streams, output length); back-reference sources are left out."""
    read = {src, src + 1}
    h = d[src] | d[src + 1] << 8
    if h == 0:
        return read, 0
    lit, ctl, n_out = src + 2, src + h, 0
    read.add(ctl)
    flags = d[ctl] | 0x100
    ctl += 1
    while len(read) < 0x10000:
        if flags & 1:
            if flags == 1:                            # sentinel: next flag byte
                read.add(ctl)
                flags = d[ctl] | 0x100
                ctl += 1
                continue
            read.add(lit)
            lit += 1
            n_out += 1
        else:
            read |= {ctl, ctl + 1}
            c = d[ctl] << 8 | d[ctl + 1]
            ctl += 2
            if c == 0:
                return read, n_out
            n = c >> 12
            if n == 0:
                read.add(ctl)
                n = d[ctl] + 16
                ctl += 1
            n_out += n + 2
        flags >>= 1
    return read, -1


def anim_script_bytes(d, s, limit=0x400):
    """Bytes the sprite animation interpreter (USA 0x0800AA94: op = s[pos], arg = s[pos+1], pos += 2; op 0xEF..0xFF
    through a 17-entry jump table) reads from script s: commands until 0xEF (stop), 0xF1 (hold: pos -= 2) or 0xFD
    (pos = arg, followed). Returns (set of offsets, terminated)."""
    seen, todo = set(), [0]
    while todo:
        pos = todo.pop()
        while pos not in seen:
            if pos >= limit:
                return set(), False
            seen.add(pos)
            op, arg = d[s + pos], d[s + pos + 1]
            if op in (0xEF, 0xF1):
                break
            if op == 0xFD:
                todo.append(arg)
                break
            pos += 2
    return {s + p + k for p in seen for k in (0, 1)}, True


ANIM_COUNT = 5      # descriptor byte: animation count (set_anim: ldrb r3,[desc,#5]; cmp r6,r3; bge; USA 0x0800BA0C)


def anim_interpreter(flow):
    """Address of the interpreter's dispatch (`subs rX,#0xef; ...; cmp rX,#0x10; bhi`), None if it is missing."""
    for o, ins in flow.insns.items():
        if ins.mnemonic == "subs" and ins.op_str.endswith("#0xef"):
            for k in (2, 4, 6):
                n = flow.insns.get(o + k)
                if n is not None and n.mnemonic == "cmp" and n.op_str == ins.op_str.split(",")[0] + ", #0x10":
                    return o + ROM
    return None


def sprite_tables(flow, end):
    """Tables returned by getter functions (RetFlow summaries) with their bound: entries while every field the code
    uses as an address holds a ROM address or 0. Returns {T: (stride, entries, pointer field offsets)}."""
    d = flow.d
    ptr_fields = collections.defaultdict(set)
    for src in flow.ev_ptr:
        if src and src[0] == "fld":
            ptr_fields[(src[1], src[2])].add(src[3])
    out = {}
    for f, v in flow.summary.items():
        if v[0] != "idx":
            continue
        T, s = v[1] - ROM, v[2]
        offs = ptr_fields.get((T, s))
        if not offs:
            continue
        n = 0
        while T + s * (n + 1) <= end and all(u32(d, T + s * n + o) == 0 or flow.is_rom(u32(d, T + s * n + o))
                                              for o in offs):
            n += 1
        out[T] = (s, n, sorted(offs))
    return out


def stores_of(flow, o, reg, steps=16):
    """Object fields a loaded register is stored to: {(store offset, displacement)}, following both ways of
    conditional branches until the register is overwritten, a call, or a return (as long as it holds the value)."""
    out, work, seen = set(), [(o + 2, 0)], set()
    while work:
        pc, n = work.pop()
        if pc in seen or n > steps or pc not in flow.insns:
            continue
        seen.add(pc)
        ins = flow.insns[pc]
        m, ops = ins.mnemonic, ins.operands
        if m == "str" and len(ops) == 2 and ops[1].type == 3 and flow.md.reg_name(ops[0].reg) == reg \
                and flow.md.reg_name(ops[1].mem.base) not in ("sp", "pc") and not ops[1].mem.index:
            out.add((pc, ops[1].mem.disp))
        if m in ("bl", "bx") or m == "pop" and "pc" in ins.op_str or m == "mov" and ins.op_str.startswith("pc"):
            continue
        if ops and ops[0].type == 1 and flow.md.reg_name(ops[0].reg) == reg and not m.startswith(("str", "cmp", "tst")):
            continue                                  # overwritten
        nxt = [pc + 2]
        if m.startswith("b") and ops and ops[0].type == 2:
            t = ops[0].imm - flow.base
            nxt = [t] if m == "b" else [t, pc + 2]
        work += [(x, n + 1) for x in nxt]
    return out


def list_consumers(flow, disp):
    """Sites that load a word list pointer from an object field and pass an entry to a function: `ldr rA,[rB,#disp]`
    followed (within 4 instructions) by `ldr r0,[rX,rA]` (rX = index * 4) and a call within 4 more instructions
    (the sprite frame list: entry = compressed frame, r0 of the decoder call)."""
    out = []
    for o, ins in flow.insns.items():
        if ins.mnemonic != "ldr" or len(ins.operands) != 2 or ins.operands[1].type != 3:
            continue
        mem = ins.operands[1].mem
        if mem.disp != disp or mem.index or flow.md.reg_name(mem.base) in ("pc", "sp"):
            continue
        ra = flow.md.reg_name(ins.operands[0].reg)
        for k in range(1, 5):
            n = flow.insns.get(o + 2 * k)
            if n is None:
                break
            if n.mnemonic == "ldr" and len(n.operands) == 2 and n.operands[1].type == 3 and n.operands[1].mem.index \
                    and ra in (flow.md.reg_name(n.operands[1].mem.base), flow.md.reg_name(n.operands[1].mem.index)):
                if flow.md.reg_name(n.operands[0].reg) == "r0" and any(
                        (flow.insns.get(o + 2 * (k + j)) or n).mnemonic == "bl" for j in range(1, 5)):
                    out.append((o, o + 2 * k))
                break
            if n.op_str.split(",")[0] == ra:
                break
    return out


# ---------------------------------------------------------------------------------------------- classifier --
def classify(gs1_path, probe_path=None, usa_path=None):
    """({word offset: (class, detail)} for the words of CATS, wordmap categories, extras)."""
    import gsfs
    cat, meta = wordmap.account(gs1_path, probe_path)
    probe = wordmap.load_probe(probe_path)
    g = Rom(gs1_path)
    gp = profiles.profile_gs1(gs1_path)
    d, size, end = g.data, len(g.data), gp["code_end"]
    is_rom = lambda v: ROM <= v < ROM + size
    sel = sorted(a for a, c in cat.items() if c in CATS)

    parts = {}
    reloc.analyse(g, end, parts=parts)
    code, switches = extended_code(g, end, parts)
    stubs = reloc.stub_targets(g, end)
    flow = RetFlow(g, end, code, stubs).run()
    ptr_ev, data_ev = flow.words()
    loads = {}
    for h in code:
        if d[h + 1] & 0xF8 == 0x48:
            loads.setdefault(((h + 4) & ~3) + d[h] * 4, h)
    chains = stub_chains(g, end)
    imports = mapcode_imports(g, gp)
    bls = collections.defaultdict(list)
    for h in code:
        hi, lo = d[h] | d[h + 1] << 8, d[h + 2] | d[h + 3] << 8
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            off = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
            bls[h + 4 + (off - 0x800000 if off & 0x400000 else off)].append(h)
    arm_e = arm_entries(g, gp, flow)
    arm_l = arm_literals(d, arm_e, end)
    # ARM code reading jump-table words through a base register (ldr ip,[sb,#k] with sb = table address)
    arm_base_reads = {}
    for la, uses in arm_l.items():
        v = u32(d, la) - ROM
        if v in chains or v + 4 in chains:
            for pc, reg, _ in uses:
                for k in range(1, 0x80):
                    ins = next(ARM.disasm(d[pc + 4 * k:pc + 4 * k + 4], ROM + pc + 4 * k), None)
                    if ins is None or ins.mnemonic == "bx" and ins.op_str == "lr":
                        break
                    if ins.mnemonic == "ldr" and ", [" in ins.op_str \
                            and ins.op_str.split(", ", 1)[1].startswith(f"[{reg}, #"):
                        arm_base_reads[v + ins.operands[1].mem.disp] = (pc + 4 * k, la)

    # sprite tables: getter-returned tables; a field stored into an object whose field is used as a word list
    tabs = sprite_tables(flow, end)
    gfx_fields, lists = {}, {}
    for (T, s, off), ld in flow.field_loads.items():
        if T not in tabs or tabs[T][0] != s or (T, off) in gfx_fields:
            continue
        for o, reg in sorted(ld):
            for at, disp in sorted(stores_of(flow, o, reg)):
                cons = list_consumers(flow, disp)
                if cons and (T, off) not in gfx_fields:
                    gfx_fields[(T, off)] = (disp, at + ROM, cons)
    ctype = collections.defaultdict(set)
    for (T, off) in gfx_fields:
        s, n, _ = tabs[T]
        for i in range(n):
            v = u32(d, T + s * i + off)
            if not v:
                continue
            L = v - ROM
            ctype[L].add(d[T + s * i + 10])
            a, run = L, []
            while is_rom(u32(d, a)):
                run.append(a)
                a += 4
            if u32(d, a) == 0:                        # the list ends with a 0 word
                for x in run:
                    lists[x] = (L, T + s * i)
    # frame data: a stream counts as read byte-wise when the decoder emulation ends exactly where the next frame
    # (or the frame list) starts (up to 3 bytes alignment padding)
    bounds = sorted({u32(d, a) - ROM for a in lists} | {L for L, _ in lists.values()})
    stream, frame_of = {}, {}
    for a, (L, e) in lists.items():
        f = u32(d, a) - ROM
        k = bisect.bisect_right(bounds, f)
        nxt = bounds[k] if k < len(bounds) else None
        frame_of[f] = (nxt, ctype.get(L, set()), e)
    for f, (nxt, kinds, e) in frame_of.items():
        wh = d[e] * d[e + 1]                          # descriptor bytes 0, 1: width, height (8 bpp frames)
        if nxt is None:
            continue
        if kinds == {1} and d[f] in (0, 1):
            try:
                pix, stop = gsfs.decompress_span(d, f)
            except (ValueError, IndexError):
                continue
            if len(pix) != wh or not 0 <= nxt - stop <= 3:
                continue
            rng = range(f, stop)
            how = (f"GS format {d[f]} stream (decoder 0x08005340) decodes to {wh} bytes = width*height and ends at "
                   f"the next frame")
        elif kinds == {3} and d[f] | d[f + 1]:
            rng, n = frame_extent_c3(d, f)
            if n < 0 or not 0 <= nxt - (max(rng) + 1) <= 3:
                continue
            how = "stage-1 literal/control streams of decode3 (0x0800A97C), ending at the next frame"
        else:
            continue
        for x in rng:
            stream.setdefault(x, (f, how))
    in_frame = {}
    for f, (nxt, kinds, e) in frame_of.items():
        if nxt is not None and nxt - f < 0x4000:
            for x in range(f, nxt):
                in_frame.setdefault(x, (f, nxt, kinds))

    # animation: the getter table's other pointer field points to a list of script pointers (scripts first, then
    # the list); list entries point between the end of the previous list and themselves (unused slots point into
    # the list itself, e.g. USA 0x081897EC); scripts parse to a stop command
    interp = anim_interpreter(flow)
    anim_lists, anim_tail, script = {}, {}, {}
    for T, (s, n, offs) in tabs.items():
        for off in offs:
            if (T, off) in gfx_fields or interp is None:
                continue
            count = collections.defaultdict(int)          # set_anim(i) checks i < descriptor byte 5 (0x0800BA0E)
            for i in range(n):
                v = u32(d, T + s * i + off)
                if v:
                    count[v - ROM] = max(count[v - ROM], d[T + s * i + ANIM_COUNT])
            prev_end = T + s * n
            for L in sorted(count):
                a = L
                while prev_end <= u32(d, a) - ROM <= a:      # scripts before the list (or the list itself)
                    if (a - L) // 4 < count[L]:
                        anim_lists[a] = L
                        r, ok = anim_script_bytes(d, u32(d, a) - ROM)
                        for x in r:
                            script.setdefault(x, u32(d, a) - ROM)
                    else:
                        anim_tail[a] = L
                    a += 4
                prev_end = max(prev_end, a)

    # ARM `ldr rX,[pc]` in ARM code that no known entry reaches (e.g. routines copied by unreached Thumb code)
    arm_lu = {}
    for a in sel:
        for b in range(max(0, a - 0x1000), min(end - 3, a + 0x1000), 4):
            w = u32(d, b)
            if w & 0x0F7F0000 == 0x051F0000 and w >> 28 == 0xE \
                    and b + 8 + ((w & 0xFFF) if w & 0x00800000 else -(w & 0xFFF)) == a:
                arm_lu[a] = b
                break

    wide = {}
    for src, sites in flow.wide_loads.items():
        for x in flow._spread(src, want_ptr=True):
            wide.setdefault(x, min(sites))

    manual = manual_map(g, usa_path) if usa_path else MANUAL.get(g.code, {})

    out = {}
    for a in sel:
        pe = probe.get(a)
        note = f"probe: {pe[1]} wide reads, none used" if pe and pe[1] else "not read in the probe tour"
        gfx = next(((T, off) for (T, off) in gfx_fields if (a - T - off) % tabs[T][0] == 0
                    and 0 <= (a - T - off) // tabs[T][0] < tabs[T][1]), None)
        if a in code or a + 2 in code:
            out[a] = ("data:code", "inside Thumb code confirmed via switch case blocks: "
                      + " / ".join(f"{d[a + k] | d[a + k + 1] << 8:04x}" for k in (0, 2)))
        elif a in chains:
            refs = []
            if bls.get(a - 4):
                refs.append(f"BL from confirmed code {bls[a - 4][0] + ROM:#x}")
            if imports.get(a - 4):
                refs.append(f"imported by {imports[a - 4]} map code stub(s)")
            if a in arm_base_reads:
                refs.append(f"read by ARM code {arm_base_reads[a][0] + ROM:#x}")
            if pe and pe[1]:
                refs.append(f"executed in the probe tour ({pe[1]} wide reads)")
            out[a] = ("pointer:jump-table", f"export table at {chains[a] + ROM:#x} (ldr r4,[pc,#0]; bx r4); "
                      + ("; ".join(refs) if refs else "no caller found"))
        elif a in loads:
            u = dict(flow.lit_use.get(a, {}))
            kind = ("pointer:literal" if set(u) & {"addr", "arg-deref", "jump", "swi", "dma"} else
                    "data:literal-number" if u and set(u) <= {"cmp", "arith"} else "pointer:literal-passed")
            out[a] = (kind, f"loaded by {loads[a] + ROM:#x} (confirmed after following switch tables), use {u}")
        elif a in arm_l and any(x[2] == "address" for x in arm_l[a]):
            pc, reg, _ = next(x for x in arm_l[a] if x[2] == "address")
            ent = max(e for e in arm_e if e <= pc)
            out[a] = ("pointer:arm-literal", f"ARM ldr {reg} at {pc + ROM:#x} (routine {ent + ROM:#x}: {arm_e[ent]}),"
                      f" {reg} used as address")
        elif a in arm_base_reads:
            out[a] = ("pointer:jump-table", f"read by ARM code {arm_base_reads[a][0] + ROM:#x} as a call target")
        elif a in data_ev and _data_in_bounds(data_ev[a][0], a, tabs):
            why = data_ev[a][1]
            out[a] = ("data:field", f"{why[0]} width {why[1]} at {why[2]:#x}, source {_src(data_ev[a][0])}")
        elif a in ptr_ev and _ptr_in_bounds(ptr_ev[a][0], a, tabs):
            why = ptr_ev[a][1]
            out[a] = ("pointer:field", f"{why[0]} at {why[1]:#x}, source {_src(ptr_ev[a][0])}")
        elif gfx:
            T, off = gfx
            disp, at, cons = gfx_fields[gfx]
            out[a] = ("pointer:field", f"table {T + ROM:#x} (stride {tabs[T][0]}, {tabs[T][1]} entries) +{off}: stored "
                      f"to object+{disp} at {at:#x}; object+{disp} indexed as word list at {cons[0][0] + ROM:#x}")
        elif a in anim_lists:
            i = (a - anim_lists[a]) // 4
            out[a] = ("pointer:anim-list", f"entry {i} of animation list {anim_lists[a] + ROM:#x}"
                      f" (descriptor field): set_anim loads list[i] (i < descriptor byte 5) into the object's script "
                      f"pointer, which the interpreter reads byte-wise")
        elif a in anim_tail:
            out[a] = ("structural:anim-list-tail", f"after the last used entry of list {anim_tail[a] + ROM:#x} "
                      f"(index >= descriptor byte 5 of every descriptor using it); {note}")
        elif all(x in script for x in range(a, a + 4)):
            out[a] = ("data:anim-script", f"bytes of animation script {script[a] + ROM:#x}, read with ldrb by the "
                      f"interpreter (dispatch {interp:#x})")
        elif a in lists:
            L, e = lists[a]
            out[a] = ("pointer:frame-list", f"entry of 0-terminated frame list {L + ROM:#x} (descriptor "
                      f"{e + ROM:#x}); {note}")
        elif all(x in stream for x in range(a, a + 4)):
            f, how = stream[a]
            out[a] = ("data:frame-stream", f"inside frame {f + ROM:#x}: {how}")
        elif all(x in in_frame for x in range(a, a + 4)):
            f, nxt, kinds = in_frame[a]
            out[a] = ("structural:in-frame-data", f"between frame {f + ROM:#x} and the next frame {nxt + ROM:#x} "
                      f"(compression type {sorted(kinds)}; stream end not verified); {note}")
        elif a in wide:
            out[a] = ("structural:loaded-32bit", f"loaded 32-bit by confirmed code at {wide[a] + ROM:#x} (value stored "
                      f"or passed on, use not traced); {note}")
        elif a in manual:
            out[a] = manual[a]
        elif (ul := unreached_loader(d, a, code)):
            out[a] = ("structural:unreached-literal", f"literal of `ldr` at {ul[0] + ROM:#x} in function "
                      f"{ul[1] + ROM:#x}"
                      f", which no confirmed code reaches; {note}")
        elif a in arm_lu:
            out[a] = ("structural:unreached-literal", f"literal of ARM `ldr` at {arm_lu[a] + ROM:#x}, routine not "
                      f"copied/called by confirmed code; {note}")
        else:
            out[a] = ("unknown", note)
    extra = {"tables": tabs, "gfx_fields": gfx_fields, "lists": lists, "switches": switches, "arm_entries": arm_e,
             "arm_literals": arm_l, "anim_lists": anim_lists, "anim_tail": anim_tail, "script": script, "code": code,
             "stream": stream, "flow": flow, "probe": probe, "loads": loads}
    return out, cat, extra


# Hand-verified words (USA offsets; other versions are mapped by the surrounding bytes in manual_map).
MANUAL = {"AGSE": {
    0x0EE9F4: ("data:field", "halfword table 0x080EE9F2 of 3 entries: `bl 0x080022FC` (IWRAM 0x030003AC, signed "
               "remainder) with r1 = 3 gives index 0..2, then ldrh [0x080EE9F2 + 2*i] at 0x080D8076; neighbour "
               "tables 0x080EE9E6/E9/EC/EF are 3-byte ldrb tables indexed the same way; word = entries 1, 2"),
    0x0F00F4: ("pointer:arm-literal", "ARM routine 0x080F0024 (DMA-copied by confirmed code, literal 0x080F0368): "
               "ldr r2,=0x080F0124 (link address of its own jump table); delta = run-time address - r2 is added to "
               "the 8 table words 0x080F0124.. (relocated by the build) -> must be relocated together with them"),
}}


def manual_map(g, usa_path):
    """MANUAL entries of the USA ROM found in another version by the 16 bytes before and after the word (the word
    itself may differ, e.g. a link address; unique match inside the program area)."""
    if g.code in MANUAL:
        return MANUAL[g.code]
    u = open(usa_path, "rb").read()
    out = {}
    for a, v in MANUAL["AGSE"].items():
        pre, post = u[a - 16:a], u[a + 4:a + 20]
        hits, i = [], g.data.find(pre, 0, g.mft_off)
        while i >= 0:
            if g.data[i + 20:i + 36] == post:
                hits.append(i + 16)
            i = g.data.find(pre, i + 1, g.mft_off)
        if len(hits) == 1:
            out[hits[0]] = (v[0], v[1] + f" (USA {a + ROM:#x}, matched by surrounding bytes)")
    return out


def side_words(cat, extra):
    """Words of other categories that the sprite evidence decides: {offset: (class, detail)} for pointer-like words
    whose build decision contradicts it (data relocated, pointer not relocated)."""
    relocated = lambda c: c.startswith(("guess", "probe-pointer", "literal", "typed-pointer", "mft", "music",
                                        "text-ptr", "SUSPECT-typed-data", "SUSPECT-code", "SUSPECT-sample",
                                        "SUSPECT-text", "SUSPECT-music", "SUSPECT-file-relocated"))
    out = {}
    for a, c in cat.items():
        if c in CATS:
            continue
        if a in extra["lists"] or a in extra["anim_lists"]:
            if not relocated(c):
                out[a] = ("pointer:" + ("frame-list" if a in extra["lists"] else "anim-list"),
                          f"sprite list entry, NOT relocated (category {c})")
        elif a in extra["anim_tail"]:
            continue                                  # unused list slot (may also be bytes of a garbage script)
        elif all(x in extra["script"] for x in range(a, a + 4)):
            if relocated(c):
                out[a] = ("data:anim-script", f"bytes of animation script {extra['script'][a] + ROM:#x}, relocated "
                          f"(category {c})")
        elif all(x in extra["stream"] for x in range(a, a + 4)):
            if relocated(c):
                out[a] = ("data:frame-stream", f"inside frame {extra['stream'][a][0] + ROM:#x}, relocated "
                          f"(category {c})")
    return out


def _src(src):
    return f"word {src[1] + ROM:#x}" if src[0] == "at" else f"table {src[1] + ROM:#x} stride {src[2]} +{src[3]}"


def _data_in_bounds(src, a, tabs):
    """Data evidence counts if it names the word exactly or lies inside a table of known extent (getter tables)."""
    if src[0] == "at":
        return True
    _, T, s, off = src
    if T not in tabs or tabs[T][0] != s:
        return False
    i = (a - T - off + 3) // s
    return 0 <= i < tabs[T][1] and (T + i * s + off) & ~3 == a


def _ptr_in_bounds(src, a, tabs):
    if src[0] == "at" or src[1] not in tabs:
        return True                                   # typeflow spreads pointer fields only over pointer-like words
    _, T, s, off = src
    return (a - T - off) // s < tabs[T][1]


if __name__ == "__main__":
    opts, args, it = {}, [], iter(sys.argv[1:])
    for x in it:
        if x in ("--usa", "--list", "--tsv"):
            opts[x] = next(it)
        else:
            args.append(x)
    usa = opts.get("--usa")
    res, cat, extra = classify(args[0], args[1] if len(args) > 1 else None, usa)
    cnt = collections.Counter(c for c, _ in res.values())
    for k in sorted(cnt):
        print(f"  {k:30s} {cnt[k]:6d}")
    if "--tsv" in opts:
        tsv = opts["--tsv"]
        d = open(args[0], "rb").read()
        lang = os.path.splitext(os.path.basename(args[1]))[0] if len(args) > 1 else Rom(args[0]).code
        rows = [(a, c, why, cat[a]) for a, (c, why) in res.items() if not c.startswith("pointer")]
        rows += [(a, c, why, cat[a]) for a, (c, why) in side_words(cat, extra).items()]
        with open(tsv, "a", encoding="utf-8", newline="\n") as f:
            for a, c, why, wc in sorted(rows):
                f.write(f"{lang}\t{a:06x}\t{u32(d, a):08x}\t{wc}\t{c}\t{why}\n")
    if "--list" in opts:
        want = opts["--list"]
        d = open(args[0], "rb").read()
        for a, (c, why) in sorted(res.items()):
            if c.startswith(want):
                print(f"{a:06x} {u32(d, a):08x} {cat[a][6:9]} {c:24s} {why}")
