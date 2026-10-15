"""Record tables that map code files hand to the engine through their exports (static, no emulator).

A map code file (unpacked to 0x02008000) starts with a jump table of exports: `ldr r4,[pc,#0]; bx r4; .word fn`.
The engine calls export k as `ldr rX,=0x02008000; ldr r0,[rX,#4+8k]; bl call_via_r0` and then walks the table the
export returns itself. The record layout per export slot is taken from that engine code (in every ROM version):
the register holding the result, `adds rT,#stride` (or ldm rT!), and the loads through rT with their widths
(constant index registers followed). Slots handled (USA engine sites):

  0x24  stride 12: +0 u32 (-1 = end, checked before each record), +4 s16, +6 s16, +8 u32  (0x0808EA2A, 0x0808F3B2)
  0x0C  stride 24: halfwords +0..+20 (s16 -1 at +0 = end)                                 (0x0808CF96, 0x0808CFD2)

The export functions may choose between several tables (story state), so every map-local address the export
function loads is a candidate table; a candidate counts only if its records parse up to the end marker. A word is
data if the engine reads a field inside it narrower than 32 bits (a pointer field is never read as a halfword).

  python mapexports.py GS1.gba
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG
import profiles, reloc
from gsfs import Rom

ROM, MAP_BASE = 0x08000000, 0x02008000
WIDTH = {"ldr": 4, "ldrh": 2, "ldrsh": 2, "ldrb": 1, "ldrsb": 1}
END = {0x24: ("u32", 0), 0x0C: ("s16", 0)}            # end marker (-1) per slot: type, offset


def _md():
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    return md


def engine_sites(d, end):
    """{slot: [bl offset]}: `ldr rX,=0x02008000; ldr r0,[rX,#slot]; bl ...`."""
    md = _md()
    out = collections.defaultdict(list)
    for h in range(0, end - 8, 2):
        i = d[h] | d[h + 1] << 8
        if i & 0xF800 != 0x4800:
            continue
        la = ((h + 4) & ~3) + (i & 0xFF) * 4
        if la + 4 > len(d) or struct.unpack_from("<I", d, la)[0] != MAP_BASE:
            continue
        ins = list(md.disasm(d[h:h + 8], ROM + h))
        if len(ins) == 3 and ins[1].mnemonic == "ldr" and ins[2].mnemonic == "bl" \
                and md.reg_name(ins[1].operands[0].reg) == "r0" and ins[1].operands[1].type == ARM_OP_MEM \
                and ins[1].operands[1].mem.base == ins[0].operands[0].reg:
            out[ins[1].operands[1].mem.disp].append(h + 4)
    return out


def layout(d, site, n=160):
    """(strides, {field offset: widths}) of the table returned by the call at `site` (straight-line scan)."""
    md = _md()
    alias, const = {"r0"}, {}
    reads, strides = collections.defaultdict(set), set()
    for x in md.disasm(d[site + 4:site + 4 + 2 * n], ROM + site + 4):
        ops = x.operands
        rn = lambda o: md.reg_name(o.reg)
        if x.mnemonic == "pop" and "pc" in x.op_str:
            break
        if x.mnemonic in WIDTH and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            base = md.reg_name(ops[1].mem.base)
            if base in alias:
                if ops[1].mem.index == 0:
                    reads[ops[1].mem.disp].add(WIDTH[x.mnemonic])
                elif md.reg_name(ops[1].mem.index) in const:
                    reads[const[md.reg_name(ops[1].mem.index)]].add(WIDTH[x.mnemonic])
        if x.mnemonic == "ldm" and rn(ops[0]) in alias:
            reads[0].add(4)
            strides.add(4 * (len(ops) - 1))
        if x.mnemonic in ("adds", "add") and len(ops) == 2 and ops[1].type == ARM_OP_IMM and rn(ops[0]) in alias:
            strides.add(ops[1].imm)
            continue
        if x.mnemonic in ("adds", "mov") and len(ops) >= 2 and ops[1].type == ARM_OP_REG and rn(ops[1]) in alias \
                and (len(ops) == 2 or ops[2].type == ARM_OP_IMM and ops[2].imm == 0):
            alias.add(rn(ops[0]))
            continue
        if x.mnemonic == "bl":
            alias -= {"r0", "r1", "r2", "r3"}
            for r in ("r0", "r1", "r2", "r3"):
                const.pop(r, None)
        if ops and ops[0].type == ARM_OP_REG and x.mnemonic not in ("cmp", "cmn", "tst", "str", "strh", "strb", "push"):
            alias.discard(rn(ops[0]))
            const.pop(rn(ops[0]), None)
        if x.mnemonic == "movs" and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
            const[rn(ops[0])] = ops[1].imm
    return strides, reads


def slot_layouts(d, end):
    """{slot: (stride, {offset: widths})} for the handled slots (merged over all engine sites)."""
    out = {}
    for slot, sites in engine_sites(d, end).items():
        if slot not in END:
            continue
        strides, reads = set(), collections.defaultdict(set)
        for s in sites:
            st, rd = layout(d, s)
            strides |= st
            for k, v in rd.items():
                reads[k] |= v
        if len(strides) == 1:
            out[slot] = (strides.pop(), dict(reads), sites)
    return out


def export_tables(b, slot):
    """Map-local addresses the export function at `slot` loads (candidate tables)."""
    if b[slot - 4:slot] != reloc.STUB:
        return set()
    fn = (struct.unpack_from("<I", b, slot)[0] & ~1) - MAP_BASE
    md = _md()
    out = set()
    for x in md.disasm(b[fn:fn + 160], MAP_BASE + fn):
        if x.mnemonic == "ldr" and x.operands[1].type == ARM_OP_MEM and md.reg_name(x.operands[1].mem.base) == "pc":
            la = ((x.address + 4) & ~3) + x.operands[1].mem.disp - MAP_BASE
            if 0 <= la <= len(b) - 4:
                v = struct.unpack_from("<I", b, la)[0] - MAP_BASE
                if 0 <= v < len(b):
                    out.add(v)
        if x.mnemonic == "bx" or x.mnemonic == "pop" and "pc" in x.op_str:
            break
    return out


def proofs(path):
    """{(file, word offset): reason} for words the engine reads as narrow record fields."""
    g = Rom(path)
    gp = profiles.profile_gs1(path)
    d = g.data
    lays = slot_layouts(d, gp["code_end"])
    out = {}
    for i in range(*gp["mapcode"]):
        b = g.decompressed(i)
        for slot, (stride, reads, sites) in lays.items():
            kind, eo = END[slot]
            narrow = {o for o, ws in reads.items() if max(ws) < 4}
            for T in export_tables(b, slot):
                recs, ok = [], False
                for k in range(512):
                    r = T + stride * k
                    if r + stride > len(b):
                        break
                    v = struct.unpack_from("<i" if kind == "u32" else "<h", b, r + eo)[0]
                    if v == -1:
                        ok = True
                        break
                    recs.append(r)
                if not ok:
                    continue
                for r in recs:
                    for a in range(r & ~3, r + stride, 4):
                        hit = [o for o in narrow if a <= r + o < a + 4]
                        if hit and r + max(reads) < len(b):
                            out.setdefault((i, a), f"export slot {slot:#x} record {r:#x} +{hit[0]:#x} read as "
                                                   f"{min(reads[hit[0]])}-byte field (engine {ROM + sites[0]:#010x})")
    return out, lays


if __name__ == "__main__":
    p, lays = proofs(sys.argv[1])
    for slot, (stride, reads, sites) in sorted(lays.items()):
        print(f"slot {slot:#x}: stride {stride}, fields {dict(sorted((k, sorted(v)) for k, v in reads.items()))}, "
              f"sites {[hex(ROM + s) for s in sites]}")
    print("narrow record words:", len(p))
