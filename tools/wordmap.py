"""Word accounting for the GS1 relocation: every word whose value looks like a GS1 ROM address gets exactly one
category with its evidence, so the remaining risk is a counted list instead of a guess.

A word is "pointer-like" if its value lies in 0x08000000..0x08000000+size (only those can need relocation).
Categories (first match wins):
  mft, music, text-ptr        relocated, proven by a format parser
  literal                     relocated, loaded PC-relative by code reached from trusted roots
  probe-pointer / probe-data  the pointer probe saw it used as an address / read byte-wise (exclusion list)
  code                        part of an instruction (not relocated)
  text-data, music-data       inside text / music track data (not relocated)
  mapcode-file                inside a compressed map code file (handled after decompression)
  guess-*                     relocated by a heuristic only (run, strided, single, literal-scan)
  file-noise / data-noise     not relocated, value hits no known target (random bytes)
  SUSPECT-*                   value equals a known target but the word is not relocated / a guess points nowhere

Known targets = values of proven pointers, MFT file starts and function entries (BL targets, odd prologues).

  python wordmap.py GS1.gba [probe.txt] [--list CATEGORY]
"""
import bisect, collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom
import build_gs1_reloc, m4a, profiles, reloc

ROM = 0x08000000


def load_probe(path):
    ev = {}
    if path and os.path.exists(path):
        for line in open(path):
            a, narrow, wide, used = line.split()
            ev[int(a, 16) - 0x09000000] = (int(narrow), int(wide), int(used))
    return ev


def account(gs1_path, probe_path=None):
    g = Rom(gs1_path)
    d, size = g.data, len(g.data)
    gp = profiles.profile_gs1(gs1_path)
    info = {}
    relocs = build_gs1_reloc.classify(g, gp, info=info)
    p = info["parts"]
    code_end = gp["code_end"]
    u32 = lambda a: struct.unpack_from("<I", d, a)[0]
    ptrlike = [a for a in range(0, size - 3, 4) if ROM <= u32(a) < ROM + size]

    stubs = reloc.stub_targets(g, code_end)            # engine jump tables: trusted function entries
    code = reloc.strict_code(d, stubs, code_end, p["roots"] - stubs, p["runs"] | p["strided"])
    lit_proven = set()
    for h in code:
        ins = d[h] | d[h + 1] << 8
        if ins & 0xF800 == 0x4800:
            lit_proven.add(((h + 4) & ~3) + (ins & 0xFF) * 4)
    music = set(info["music"])
    music_bytes = {o + k for o in info["music"] for k in range(4)}
    text = info["text"]
    text_ptrs = set(text["pointers"])
    mft_table = set(p["mft"])
    mft_end = g.mft_off + 4 * len(g.entries)
    files = sorted(set(g.entries))
    mapcode = set(g.entries[i] for i in range(*gp["mapcode"]))
    probe = load_probe(probe_path)

    proven = mft_table | music | text_ptrs | (lit_proven & set(relocs))
    targets = {u32(a) & ~1 for a in proven}
    targets |= {ROM + e for e in g.entries}
    targets |= {ROM + t for t in reloc.bl_targets(d, 0, code_end)}
    targets |= {ROM + r for r in p["roots"]}

    # table structure around each pointer-like word: run length (pointer-like or 0), share of targets near the
    # table, share of byte-like values (low three bytes < 0x20, e.g. 08 09 09 09)
    table = {}
    pset = set(ptrlike)
    i = 0
    while i < len(ptrlike):
        s0 = ptrlike[i]
        e = s0
        while e + 4 in pset or (e + 8 in pset and u32(e + 4) == 0):
            e += 4
        run = [x for x in range(s0, e + 4, 4) if x in pset]
        vals = [u32(x) for x in run]
        near = sum(abs((v & ~1) - ROM - x) < 0x40000 for v, x in zip(vals, run)) * 2 > len(run)
        bl = sum(all(((v >> sh) & 0xFF) < 0x20 for sh in (0, 8, 16)) for v in vals) * 2 > len(run)
        for x in run:
            table[x] = (len(run), near, bl)
        while i < len(ptrlike) and ptrlike[i] <= e:
            i += 1

    cat = {}
    for a in ptrlike:
        w = u32(a)
        hit = (w & ~1) in targets
        r = a in relocs
        pe = probe.get(a)
        if a in mft_table:
            c = "mft"
        elif a in music:
            c = "music"
        elif a in text_ptrs:
            c = "text-ptr"
        elif r and a in lit_proven:
            c = "literal"
        elif a in info["ptr_ev"]:
            c = "typed-pointer" if r else "SUSPECT-typed-pointer-not-relocated"
        elif a in info["data_ev"]:
            c = "typed-data" if not r else "SUSPECT-typed-data-relocated"
        elif pe and pe[2]:
            c = "probe-pointer" if r else "SUSPECT-probe-used-not-relocated"
        elif pe and pe[0] and not r:
            c = "probe-data"
        elif a in code or a + 2 in code:
            c = "code" if not r else "SUSPECT-code-relocated"
        elif text["data_start"] <= a < text["data_end"]:
            c = "text-data" if not r else "SUSPECT-text-relocated"
        elif any(a + k in music_bytes for k in range(4)) or a in info["music_overlap"]:
            c = "music-data" if not r else "SUSPECT-music-relocated"
        elif a >= mft_end:
            f = files[bisect.bisect_right(files, a) - 1]
            if f in mapcode:
                c = "mapcode-file"
            elif r:
                c = "SUSPECT-file-relocated"
            else:
                c = "SUSPECT-file-hits-target" if hit else "file-noise"
        elif r:
            n, near, bytelike = table[a]
            if bytelike:
                c = "guess-WEAK-bytelike"              # 08 09 09 09 ...: looks like byte data
            elif n >= 4 and near:
                c = "guess-table"                      # >= 4 pointer-like words in a row pointing nearby
            elif n >= 3 or hit or near:
                c = "guess-plausible"
            else:
                c = "guess-WEAK-isolated"
        else:
            c = "SUSPECT-data-hits-target" if hit else "data-noise"
        cat[a] = c
    return cat, {"size": size, "code_end": code_end, "relocated": len(relocs), "ptrlike": len(ptrlike)}


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    rom, probe = args[0], (args[1] if len(args) > 1 else None)
    cat, meta = account(rom, probe)
    print(f"pointer-like words: {meta['ptrlike']}, relocated (whole uncompressed area): {meta['relocated']}")
    cnt = collections.Counter(cat.values())
    for k in sorted(cnt, key=lambda k: (k.startswith("SUSPECT"), k.startswith("guess"), k)):
        print(f"  {k:36s} {cnt[k]:6d}")
    if "--list" in sys.argv:
        want = sys.argv[sys.argv.index("--list") + 1]
        d = open(rom, "rb").read()
        for a, c in sorted(cat.items()):
            if c == want:
                print(f"{a:06x} {struct.unpack_from('<I', d, a)[0]:08x}")
