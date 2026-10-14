"""Final accounting: every pointer-like word of GS1 (program area, files, unpacked map code) with its verdict.

Combines all evidence the project has:
  program area   wordmap.py categories (format / literal / code / typeflow / probe) and the step-5 verdicts
                 (build/step5/<lang>.json from step5_collect.py)
  files          fileverify.py (file tour log + probe + filemap format proofs)
  map code       mapflow.py (jump tables, code, tables read by the map code)
Verdict: P = proven pointer, D = proven not a pointer, open = no proof (the reason says why).

  python verify_all.py LANG [--list]     (LANG = en de fr it es)
"""
import collections, contextlib, io, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROMS = {"en": "Golden Sun (USA, Europe).gba", "de": "Golden Sun (Germany).gba", "fr": "Golden Sun (France).gba",
        "it": "Golden Sun (Italy).gba", "es": "Golden Sun (Spain).gba"}
P_CATS = {"mft", "music", "text-ptr", "literal", "typed-pointer", "probe-pointer", "jump table"}
D_CATS = {"code", "text-data", "music-data", "sample-data", "probe-data", "typed-data"}


def account(lang):
    import wordmap, fileverify, mapflow, typeflow
    rom = os.path.join(ROOT, "..", "work", "goldensun", "clean", ROMS[lang])
    probe = os.path.join(ROOT, "build", "probe_all", f"{lang}.txt")
    out = {}
    with contextlib.redirect_stdout(io.StringIO()):
        cat, meta = wordmap.account(rom, probe)
    s5 = json.load(open(os.path.join(ROOT, "build", "step5", f"{lang}.json")))
    for a, c in cat.items():
        if c in ("file-noise", "mapcode-file") or c.startswith("SUSPECT-file"):
            continue                                   # files: below
        ev = {v for s, v, d in s5.get(f"{a:06x}", {}).get("ev", [])}
        if c in P_CATS or "P" in ev:
            out[("rom", a)] = ("P", c if c in P_CATS else "step5")
        elif c in D_CATS or ev & {"D", "C"}:
            out[("rom", a)] = ("D", c if c in D_CATS else "step5")
        elif "Dw" in ev:
            out[("rom", a)] = ("D", "step5 (weak bound)")
        else:
            out[("rom", a)] = ("open", c)
    import tileproof                                   # tables whose targets tile as packed streams
    tp, td = tileproof.proofs(rom)
    for a, (name, t) in tp.items():
        k = ("rom", a)
        if k in out and out[k][0] == "D":
            out[k] = ("CONFLICT", f"tiling says pointer ({name} table {t:06x}), other evidence data")
        elif k in out:
            out[k] = ("P", out[k][1] if out[k][0] == "P" else f"tiling: {name} stream table {t:06x}")
    for a, (name, t) in td.items():
        k = ("rom", a)
        if k in out and out[k][0] == "P":
            out[k] = ("CONFLICT", f"tiling says stream data ({name} table {t:06x}), other evidence pointer")
        elif k in out and out[k][0] == "open":
            out[k] = ("D", f"tiling: inside {name} stream of table {t:06x}")
    with contextlib.redirect_stdout(io.StringIO()):
        fv, req, bad = fileverify.verify(rom, os.path.join(ROOT, "build", "probe_all", f"files_{lang}.log"), probe)
    for a, v in fv.items():
        if v.startswith("mapcode"):
            continue
        out[("rom", a)] = ("open", v) if v in ("not used in the tour", "straddles a part boundary") else ("D", v)
    with contextlib.redirect_stdout(io.StringIO()):
        res = mapflow.analyse(rom)
    for i, (mf, words) in res.items():
        for a, (kind, u) in words.items():
            k = ("map", i, a)
            if kind == "jump table":
                out[k] = ("P", "map code jump table")
            elif kind == "code" or kind.startswith("table: read as bytes") or kind.startswith("table: read as 32"):
                out[k] = ("D", "map code " + kind)
            elif kind == "literal":
                out[k] = ("P" if set(u or {}) & mapflow.ADDRESS_USES else "open", "map code literal")
            else:
                out[k] = ("open", "map code " + kind)
    return out


def summary(out):
    c = collections.Counter(v for v, why in out.values())
    reasons = collections.Counter(why for v, why in out.values() if v == "open")
    return c, reasons


if __name__ == "__main__":
    lang = sys.argv[1]
    out = account(lang)
    c, reasons = summary(out)
    total = sum(c.values())
    print(f"{lang}: {total} pointer-like words; proven pointer {c['P']}, proven data {c['D']}, open {c['open']} "
          f"({100 * c['open'] / total:.1f} %)")
    for r, n in reasons.most_common():
        print(f"   open: {n:5d}  {r}")
    os.makedirs(os.path.join(ROOT, "build", "verify"), exist_ok=True)
    json.dump({"|".join(map(str, k)): v for k, v in out.items()},
              open(os.path.join(ROOT, "build", "verify", f"{lang}.json"), "w"))
