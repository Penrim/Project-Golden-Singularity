"""Match GS1 engine jump-table functions to their TLA counterparts.

Each slot function is disassembled into a normalised token sequence (mnemonics, registers, small immediates;
branch targets dropped; literal-pool constants classified). Slots of the same engine file are then aligned with
order-preserving dynamic programming (TLA inserts new slots but keeps the old order).

Usage: python fnmatcher.py GS1.gba TLA.gba out.json
"""
import json, struct, sys
from difflib import SequenceMatcher
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from gsfs import Rom

ENGINE_FILES = [3, 4, 5, 6, 8, 10, 11]
STUB = b"\x00\x4c\x20\x47"
MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def slots(rom, idx):
    base = rom.entries[idx]
    out, o = [], 0
    while rom.data[base + o:base + o + 4] == STUB:
        out.append(struct.unpack_from("<I", rom.data, base + o + 4)[0])
        o += 8
    return out


def classify_const(rom, v):
    if 0x08000000 <= v < 0x08000000 + len(rom.data):
        return "ROMPTR"
    if 0x02000000 <= v < 0x02040000:
        return "EWRAM"  # variable addresses moved between the games
    if 0x03000000 <= v < 0x03008000:
        return "IWRAM"
    if 0x04000000 <= v < 0x04000400:
        return f"IO{v:#x}"   # hardware registers are identical in both games
    return f"K{v:#x}"


def tokens(rom, fn, limit=600):
    """Disassemble a Thumb function, linear sweep until a return past the furthest forward branch."""
    start = (fn & ~1) - 0x08000000
    if not (0 <= start < len(rom.data)):
        return []
    code = rom.data[start:start + limit * 2]
    toks, far = [], start
    for ins in MD.disasm(code, 0x08000000 + start):
        m, ops = ins.mnemonic, ins.op_str
        off = ins.address - 0x08000000
        if m in ("bl", "b") or (m.startswith("b") and m not in ("bic", "bics", "bx", "blx") and "#0x" in ops):
            tgt = int(ops.lstrip("#"), 16) - 0x08000000
            if m != "bl":
                far = max(far, tgt)
            toks.append(m)
        elif m.startswith("ldr") and "pc" in ops:
            reg = ops.split(",")[0]
            lit_addr = ((ins.address + 4) & ~3) + int(ops.split("#")[-1].rstrip("]"), 16)
            lo = lit_addr - 0x08000000
            v = struct.unpack_from("<I", rom.data, lo)[0] if 0 <= lo < len(rom.data) - 4 else 0
            toks.append(f"ldr {reg},{classify_const(rom, v)}")
        else:
            toks.append(f"{m} {ops}")
        # GS1 returns via "pop {rX}; bx rX" (interworking), TLA via "pop {pc}"; normalise to one token
        if m == "bx" and ops != "lr" and toks and toks[-1].startswith("pop"):
            toks.pop()
            prev = toks.pop() if toks and toks[-1].startswith("pop {r") else "pop {"
            regs = prev[5:].rstrip("}").strip()
            toks.append("pop {" + (regs + ", " if regs else "") + "pc}")
        is_ret = (m == "pop" and "pc" in ops) or m == "bx"
        if is_ret and off >= far:
            break
        if len(toks) >= limit:
            break
    return toks


def sim(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def align(ga, ta):
    """Order-preserving alignment maximising total similarity (gaps free; matches need sim >= 0.35)."""
    n, m = len(ga), len(ta)
    S = [[sim(ga[i], ta[j]) for j in range(m)] for i in range(n)]
    D = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best = max(D[i + 1][j], D[i][j + 1])
            if S[i][j] >= 0.35:
                best = max(best, S[i][j] + D[i + 1][j + 1])
            D[i][j] = best
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if S[i][j] >= 0.35 and abs(D[i][j] - (S[i][j] + D[i + 1][j + 1])) < 1e-9:
            pairs.append((i, j, S[i][j])); i += 1; j += 1
        elif D[i][j] == D[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


def main(gpath, tpath, out):
    g, t = Rom(gpath), Rom(tpath)
    result = {"gs1": g.code, "tla": t.code, "files": {}}
    for f in ENGINE_FILES:
        gs, ts = slots(g, f), slots(t, f)
        ga = [tokens(g, x) for x in gs]
        ta = [tokens(t, x) for x in ts]
        pairs = align(ga, ta)
        strong = sum(s >= 0.8 for _, _, s in pairs)
        print(f"file {f:3d}: GS1 {len(gs):3d} / TLA {len(ts):3d} slots -> matched {len(pairs):3d} "
              f"(>=0.8: {strong}), unmatched GS1 {len(gs) - len(pairs)}")
        result["files"][f] = [
            {"gs1_slot": i, "tla_slot": j, "score": round(s, 3),
             "gs1_fn": f"{gs[i]:#x}", "tla_fn": f"{ts[j]:#x}"} for i, j, s in pairs]
    json.dump(result, open(out, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
