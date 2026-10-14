"""Proof status of GS1's pointer TABLES (wordmap category guess-table: >= 4 pointer-like words in a row pointing
nearby, relocated on heuristics only), from code use (tableflow.py) and the recorded all-words probe.

Classes per guess-table word:
  ptr-code         the program reads the word 32-bit and uses it as an address (tableflow, strict mode: no RAM
                   gcd keys, no may-merges); `via` = how: deref/jump/arg/call/sum (direct) or ram (RAM link)
  ptr-code-may     proven with may-merges (a table word reaching a merge on one path keeps its identity)
  ptr-code-gcd     proven only with RAM paths keyed by a gcd stride (array inside array elements)
  beyond-count     spread over a sprite animation table beyond its count byte (+5): not reached by the code
  ptr-probe        recorded probe: read 32-bit and used as an address
  DATA-code        code reads it byte/halfword-wise (exact word or a struct field)   -> contradiction (relocated)
  DATA-probe       probe: narrow reads only                                          -> contradiction (relocated)
  CONFLICT         pointer and data evidence
  structural       no evidence; `partly` = other words of the same run are proven pointers
Side findings: words of other categories whose evidence contradicts the build (not relocated but proven pointer,
relocated but proven data).

  python tableproof.py GS1.gba probe.txt [--list CLASS] [--save result.pkl]
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom
import reloc, tableflow, wordmap

ROM = 0x08000000
PROVEN = ("mft", "music", "text-ptr", "literal", "typed-pointer", "probe-pointer")
RELOCATED = ("mft", "music", "text-ptr", "literal", "typed-pointer", "probe-pointer", "guess-table", "guess-plausible",
             "guess-WEAK-isolated", "guess-WEAK-bytelike")
DIRECT = ("deref", "jump", "arg", "call", "sum", "dma", "swi", "iwram")


def data_kind(src):
    """exact word / struct field (stride >= 4) / byte or halfword array (extent from bounds only)."""
    if src[0] == "at" or (src[0] == "sub" and not src[2]):
        return "exact"
    stride = src[2]
    return "field" if stride >= 4 else "bytes"


def anim_beyond_count(f, p, d):
    """Sprite info table (the getter returns T + id * 0x14): +0x10 = animation table, +5 = its count (0x0800BE2A:
    ldrb r3,[r0,#5]; cmp r6,r3; blo). Spread words of that table field outside every [table, table + 4*count)."""
    u32 = lambda a: struct.unpack_from("<I", d, a)[0]
    out = set()
    for v in f.ret.values():
        if v is tableflow.CONFLICT or v[0] != "idx" or v[2] != 0x14 or not f.is_rom(v[1]):
            continue
        T = v[1] - ROM
        src = ("sub", ("fld", T + 0x10, 0x14, 0), 4, 0)
        inside = set()
        for k in range(4096):
            b = T + 0x14 * k
            if b + 0x14 > len(d) or not any(x == ("fld", T + 0x10, 0x14, 0) or x == ("fld", T, 0x14, 0x10)
                                                for x in [p.get(b + 0x10, (None,))[0]]):
                break
            w = u32(b + 0x10)
            if ROM <= w < ROM + len(d):
                inside.update(range(w - ROM, w - ROM + 4 * d[b + 5], 4))
        out |= {a for a, (s, _) in p.items() if s[0] == "sub" and s[1] in (("fld", T + 0x10, 0x14, 0),
                                                                             ("fld", T, 0x14, 0x10))
                and s[2:] == (4, 0) and a not in inside}
    return out


def runs(cat, d):
    """Maximal runs of pointer-like words (zero words allowed inside), as wordmap.account groups them."""
    u32 = lambda a: struct.unpack_from("<I", d, a)[0]
    pl = lambda a: 0 <= a <= len(d) - 4 and ROM <= u32(a) < ROM + len(d)
    out, seen = [], set()
    for a in sorted(cat):
        if cat[a] != "guess-table" or a in seen:
            continue
        s = a
        while pl(s - 4) or (s >= 8 and u32(s - 4) == 0 and pl(s - 8)):
            s -= 4
        e = a
        while pl(e + 4) or (u32(e + 4) == 0 and pl(e + 8)):
            e += 4
        seen.update(range(s, e + 4, 4))
        out.append((s, e + 4))
    return out


def analyse(rom_path, probe_path):
    cat, meta = wordmap.account(rom_path, probe_path)
    probe = wordmap.load_probe(probe_path)
    g = Rom(rom_path)
    d = g.data
    u32 = lambda a: struct.unpack_from("<I", d, a)[0]
    known = {(u32(a) & ~1) - ROM for a, c in cat.items() if c in PROVEN}
    res = {}
    for mode, may, gcd in (("strict", False, False), ("may", True, False), ("full", True, True)):
        f = tableflow.TableFlow(rom_path, may=may, gcd=gcd).run()
        p, dd = f.words(bounds=known)
        res[mode] = (p, dd, f.walked, f.inconsistent)
        if mode == "full":
            beyond = anim_beyond_count(f, p, d)
    sp, sd = res["strict"][:2]
    mp = res["may"][0]
    fp, fd, walked, inconsistent = res["full"]

    level = lambda a, ev: "strict" if a in ev[0] else "may" if a in ev[1] else "full"

    def via(a):
        why = (sp.get(a) or mp.get(a) or fp.get(a))[1]
        return why[0] if why[0] in DIRECT + ("ram",) else "other"

    cls, how = {}, {}
    for a, c in cat.items():
        if c != "guess-table":
            continue
        pr = probe.get(a)
        pp = bool(pr and pr[1] and pr[2])
        pdat = bool(pr and pr[0] and not pr[1])
        dsrc = sd.get(a) or fd.get(a)
        dat = dsrc is not None and data_kind(dsrc[0]) != "bytes"
        if (a in fp or pp) and (dat or pdat):
            cls[a] = "CONFLICT"
        elif dat:
            cls[a] = "DATA-code"
        elif pdat:
            cls[a] = "DATA-probe"
        elif a in beyond:
            cls[a] = "beyond-count"
        elif a in sp:
            cls[a] = "ptr-code"
        elif a in mp:
            cls[a] = "ptr-code-may"
        elif a in fp:
            cls[a] = "ptr-code-gcd"
        elif pp:
            cls[a] = "ptr-probe"
        else:
            cls[a] = "structural"
        if cls[a].startswith("ptr-code"):
            how[a] = via(a)
    # structural words: is another word of the same run proven?
    tables = runs(cat, d)
    proven_ptr = lambda x: cls.get(x, "").startswith("ptr") or cat.get(x) in PROVEN
    for s, e in tables:
        part = any(proven_ptr(x) for x in range(s, e, 4))
        for x in range(s, e, 4):
            if cls.get(x) == "structural" and part:
                cls[x] = "structural-partly"
    # side findings over all categories
    side = []
    for a, c in sorted(cat.items()):
        if c == "guess-table":
            continue
        reloc = c in RELOCATED or (c.endswith("-relocated") and not c.endswith("not-relocated"))
        if not reloc and a in fp:
            side.append((a, u32(a), c, "pointer evidence, NOT relocated", fp[a], level(a, (sp, mp))))
        dsrc = sd.get(a) or fd.get(a)
        if reloc and dsrc and a not in fp:
            side.append((a, u32(a), c, f"data evidence ({data_kind(dsrc[0])}), relocated", dsrc,
                         "strict" if a in sd else "full"))
    rem = remaining(cat, cls, tables, d, f.labels(), g.mft_off)
    return {"cat": cat, "cls": cls, "how": how, "tables": tables, "side": side, "remaining": rem,
            "walked": {a: w for a, w in walked.items() if a in cat}, "inconsistent": inconsistent,
            "evidence": {a: (sp.get(a) or mp.get(a) or fp.get(a) or sd.get(a) or fd.get(a)) for a in cls},
            "data": d}


def remaining(cat, cls, tables, d, labels, code_end):
    """Runs with unproven guess-table words and why they stay open."""
    u32 = lambda a: struct.unpack_from("<I", d, a)[0]
    arm_lits = set()
    for a in range(0, code_end - 3, 4):                # ARM ldr rX, [pc, #+-imm] (routines copied to RAM)
        w = u32(a)
        if w & 0x0F7F0000 == 0x051F0000 and w >> 28 == 0xE:
            imm = w & 0xFFF
            arm_lits.add(a + 8 + (imm if w & 0x00800000 else -imm))
    byval = collections.defaultdict(list)
    for a in range(0, len(d) - 3, 4):
        w = u32(a)
        if ROM <= w < ROM + len(d):
            byval[w - ROM].append(a)
    labels = set(labels)
    thumb_lits = {a for a in reloc.literal_targets(d, 0, code_end) if a not in arm_lits}
    out = []
    for s, e in tables:
        open_ = [x for x in range(s, e, 4) if cls.get(x, "").startswith("structural")]
        if not open_:
            continue
        refs = [r for t in range(s, e, 4) for r in byval.get(t, [])]
        if any(r in arm_lits for r in refs):
            why = "base is a literal of ARM code (routine copied to RAM; ARM code is not analysed)"
        elif any(t in labels for t in range(s, e, 4)):
            why = "Thumb code loads the base; the use is not traced (stored to RAM, read by untraced code)"
        elif any(r in thumb_lits for r in refs):
            why = "base is a literal of Thumb code outside the confirmed code (function not reached from the roots)"
        elif refs and all(cat.get(r, "").startswith("guess") or cls.get(r, "").startswith("structural")
                          for r in refs):
            why = "only referenced by unproven words (" + ", ".join(sorted({cat.get(r, "?") for r in refs})) + ")"
        elif refs:
            why = "referenced by " + ", ".join(sorted({cat.get(r, "?") for r in refs}))
        else:
            why = "no reference found (offset arithmetic or unreached)"
        if any(cls.get(x, "").startswith("ptr") for x in range(s, e, 4)):
            why += "; other entries proven (bound unknown)"
        out.append((s, e, len(open_), why))
    return out


def summary(r):
    return collections.Counter(r["cls"].values()), collections.Counter(r["how"].values())


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    r = analyse(args[0], args[1])
    c, v = summary(r)
    print("guess-table words:", sum(c.values()))
    for k in sorted(c):
        print(f"  {k:20s} {c[k]:6d}")
    print("  proof route of ptr-code*:", dict(v))
    print("side findings:")
    for a, w, cat, what, ev, lv in r["side"]:
        print(f"  {a:06x} {w:08x} {cat:28s} {what} [{lv}]  {ev}")
    print("open runs:")
    for s_, e, n, why in r["remaining"]:
        print(f"  {s_:06x}-{e:06x} {n:4d} open  {why}")
    if "--save" in sys.argv:
        import pickle
        pickle.dump(r, open(sys.argv[sys.argv.index("--save") + 1], "wb"))
    if "--list" in sys.argv:
        want = sys.argv[sys.argv.index("--list") + 1]
        for a, k in sorted(r["cls"].items()):
            if k == want:
                print(f"{a:06x} {struct.unpack_from('<I', r['data'], a)[0]:08x} {r['evidence'][a]}")
