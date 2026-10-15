"""Code the build's analysis does not reach, found from code shapes that prove themselves (static, no emulator).

reloc.strict_code starts at the engine's known entry points and follows calls and branches. Functions that are only
called through tables the analysis does not trust (switch tables of unreached code, function tables) stay unreached,
and so do their literal pools. This module adds two kinds of roots and iterates to a fixpoint:

  switch     `ldr rT,=TABLE ... ldr rX,[rT,rI] (or [rI,rT]); mov pc,rX` with TABLE = the word-aligned address
             right after the `mov pc` (the literal names the table that follows it: GCC's switch layout). Entries are
             the even case addresses after the table, up to the first case (a table never runs into its own code).
             The idiom and the cases become code, the table words proven pointers.
  functions  runs of odd ROM words whose every target is a Thumb function start (push {..., lr}; mov ip,lr + bl; a
             BL target of confirmed code; confirmed code right after a bx/pop {pc}/b) and whose code does not run over a table word: >= 3
             different targets, or 2 that are both confirmed code (repeated byte patterns are not tables). The words
             are proven pointers, the targets roots.
Afterwards typeflow and litproof run on the extended code, so the literal pools of the new functions get the same
proofs as the reached ones.

  python reach.py GS1.gba
"""
import collections, contextlib, io, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom
import profiles, reloc

ROM = 0x08000000


def u32(d, a):
    return struct.unpack_from("<I", d, a)[0]


def self_switches(d, end):
    """{table offset: (idiom start, [case offsets])} for every self-describing switch in [0, end)."""
    out = {}
    for h in range(0, end - 2, 2):
        ins = d[h] | d[h + 1] << 8
        if ins & 0xFF87 != 0x4687:                       # mov pc, rX
            continue
        rx = (ins >> 3) & 0xF
        T = (h + 2 + 3) & ~3
        if T + 8 > end:
            continue
        lt = None
        for k in range(1, 12):                           # ldr rT,[pc,#n] loading TABLE, a few halfwords back
            o = h - 2 * k
            if o < 0:
                break
            i = d[o] | d[o + 1] << 8
            if i & 0xF800 == 0x4800:
                la = ((o + 4) & ~3) + (i & 0xFF) * 4
                if la + 4 <= len(d) and u32(d, la) == ROM + T:
                    lt = o
                    break
        if lt is None:
            continue
        ld = d[h - 2] | d[h - 1] << 8                    # ldr rX,[rA,rB] right before the mov pc
        if ld & 0xFE00 != 0x5800 or ld & 7 != rx:
            continue
        cases, k = [], 0
        while True:
            e = T + 4 * k
            if cases and e >= min(cases) or e + 4 > end:
                break
            c = u32(d, e) - ROM
            if not (T < c < T + 0x10000) or c & 1:
                break
            cases.append(c)
            k += 1
        if len(cases) >= 2 and T + 4 * len(cases) <= min(cases):
            out[T] = (lt, cases)
    return out


def function_tables(d, end, code, tables):
    """{word offset: target} for runs of >= 3 odd ROM words that all point at Thumb function starts."""
    bls = set()
    for h in code:
        hi, lo = d[h] | d[h + 1] << 8, d[h + 2] | d[h + 3] << 8
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            off = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
            bls.add(h + 4 + (off - 0x800000 if off & 0x400000 else off))
    def helper(t):                                       # mov ip, lr; bl ...  (leaf calling a shared helper)
        return d[t] | d[t + 1] << 8 == 0x46F4 and d[t + 3] & 0xF8 == 0xF0 and d[t + 5] & 0xF8 == 0xF8

    def start(t):                                        # confirmed code that begins after a function's end
        if t not in code:
            return False
        p = d[t - 2] | d[t - 1] << 8
        return t - 2 not in code or p & 0xFF87 == 0x4700 or p & 0xFF00 == 0xBD00 or p & 0xF800 == 0xE000
    out = {}
    a = 0
    while a < end - 4:
        run = []
        b = a
        while b < end - 3:
            w = u32(d, b)
            t = (w & ~1) - ROM
            if not (w & 1 and 0 <= t < end and (t in bls or start(t) or reloc.is_prologue(d, t) or helper(t))):
                break
            run.append((b, t))
            b += 4
        ts = {t for _, t in run}
        if (len(ts) >= 3 or len(ts) == 2 and all(start(t) or t in bls for t in ts)) and all(not (b2 in code or b2 + 2 in code) for b2, _ in run):
            ok = True
            words = dict(run)
            for t in {t for _, t in run}:
                c = reloc.code_coverage(d, {t}, end)
                if any(x & ~3 in tables or x & ~3 in words for x in c):
                    ok = False
                    break
            if ok:
                out.update(run)
        a = b + 4 if b == a else b
    return out


def extend(g, end, parts=None):
    """(code, switch tables, function-table words) at the fixpoint."""
    d = g.data
    if parts is None:
        parts = {}
        with contextlib.redirect_stdout(io.StringIO()):
            reloc.analyse(g, end, parts=parts)
    stubs = reloc.stub_targets(g, end)
    tables = parts["runs"] | parts["strided"]
    sw_all = self_switches(d, end)
    roots = set(stubs)
    sw, ft = {}, {}
    while True:
        code = reloc.strict_code(d, roots, end, parts["roots"] - stubs, tables)
        new = set()
        for T, (lt, cases) in sw_all.items():            # a switch counts once its idiom or a case is reached,
            if T in sw:                                  # or when nothing reached overlaps it (self-proving)
                continue
            if any(x in code for x in range(T, T + 4 * len(cases), 2)):
                continue                                 # the table bytes are reached code: not a table
            sw[T] = cases
            new |= {lt} | set(cases)
        for w, t in function_tables(d, end, code, set(sw) | {T + 4 * k for T, c in sw.items() for k in range(len(c))}).items():
            if w not in ft:
                ft[w] = t
                new.add(t)
        if not new - roots:
            return code, sw, ft
        roots |= new


def proofs(path):
    """({word: reason} proven pointers, {word: reason} proven data, extra stats) from the extended code."""
    import litproof, typeflow
    g = Rom(path)
    gp = profiles.profile_gs1(path)
    end = gp["code_end"]
    d = g.data
    parts = {}
    with contextlib.redirect_stdout(io.StringIO()):
        reloc.analyse(g, end, parts=parts)
    stubs = reloc.stub_targets(g, end)
    base = reloc.strict_code(d, set(stubs), end, parts["roots"] - stubs, parts["runs"] | parts["strided"])
    code, sw, ft = extend(g, end, parts)
    ptr, data = {}, {}
    for T, cases in sw.items():
        for k in range(len(cases)):
            ptr[T + 4 * k] = f"switch table {T:06x}"
    for w, t in ft.items():
        ptr[w] = f"function table -> {t:06x}"
    f = typeflow.Flow(g, end, code, stubs).run()
    p_ev, d_ev = f.words()
    for a, why in p_ev.items():
        ptr.setdefault(a, f"typeflow pointer {why}"[:80])
    for a, why in d_ev.items():
        if a not in ptr:
            data.setdefault(a, f"typeflow data {why}"[:80])
    tr = litproof.Tracer(f)
    for la, (c, ev, why, nums) in litproof.classify_all(tr).items():
        if c in ("address", "function", "size-of-pointer"):
            ptr.setdefault(la, f"literal {c}")
        elif c == "number":
            if la in ptr:
                ptr[la] = "CONFLICT " + ptr[la]
            else:
                data[la] = "literal number"
    lits = set(tr.lit_sites)                             # words loaded as literals are never instructions (a case
    for a in {h & ~3 for h in code - base}:              # block ending in a bl to a no-return function falls
        if a in code and a + 2 in code and a not in lits:  # through into its literal pool)
            if a in ptr:
                ptr[a] = "CONFLICT code / " + ptr[a]
            else:
                data.setdefault(a, "code (reached via switch/function tables)")
    return ptr, data, {"base": len(base), "code": len(code), "switches": len(sw), "fn-words": len(ft)}


if __name__ == "__main__":
    p, dd, st = proofs(sys.argv[1])
    print(st)
    print("pointer words:", len(p), "data words:", len(dd), "conflicts:", sum(v.startswith("CONFLICT") for v in p.values()))
    print(collections.Counter(v.split()[0] + " " + v.split()[1] for v in p.values()).most_common(8))
    print(collections.Counter(v.split()[0] for v in dd.values()).most_common(8))
