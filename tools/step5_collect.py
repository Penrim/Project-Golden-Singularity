"""Collect the step-5 verdicts of tableproof (tables), singles (short runs), dataproof (byte data) and litproof
(literal constants) per pointer-like word, and compare them with what the build relocates.

  python step5_collect.py LANG [LANG ...]      -> build/step5/<lang>.json
Each word: list of (source, verdict, detail); verdict P = pointer, D = data (Dw = data, weak evidence), S = structural
only / unknown. Conflicts (P and D for the same word) must be resolved before any build change.
"""
import csv, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ROMS = {"en": "Golden Sun (USA, Europe).gba", "de": "Golden Sun (Germany).gba", "fr": "Golden Sun (France).gba",
        "it": "Golden Sun (Italy).gba", "es": "Golden Sun (Spain).gba"}
CODES = {"en": "AGSE", "de": "AGSD", "fr": "AGSF", "it": "AGSI", "es": "AGSS"}


def collect(lang):
    rom = os.path.join(ROOT, "..", "work", "goldensun", "clean", ROMS[lang])
    probe = os.path.join(ROOT, "build", "probe_all", f"{lang}.txt")
    out = {}
    add = lambda a, src, v, det: out.setdefault(a, []).append((src, v, det))

    import tableproof
    r = tableproof.analyse(rom, probe)
    for a, k in r["cls"].items():
        v = "P" if k.startswith("ptr") else "D" if k.startswith("DATA") else "C" if k == "CONFLICT" else "S"
        add(a, "tables", v, k)
    for a, w, cat, what, ev, lv in r["side"]:
        add(a, "tables-side", "P" if "pointer" in what.lower() and "not" in what.lower() or what.lower().startswith("pointer")
            else "D" if "data" in what.lower() else "S", f"{what} [{lv}] {ev}"[:200])

    import litproof
    for la, w, b, c, why, nums, pe, ev, odd in litproof.report(rom, probe):
        v = "P" if c in ("address", "function", "size-pair", "size end") else "D" if c == "number" else "S"
        add(la, "literals", v, c)

    for row in csv.reader(open(os.path.join(ROOT, "docs", "step5_singles_words.tsv"), encoding="utf-8"), delimiter="\t"):
        if len(row) >= 5 and row[0] == lang:
            k = row[4]
            add(int(row[1], 16), "singles", "P" if k.startswith("pointer") else "D" if k.startswith("data") else "S", k)

    for row in csv.DictReader(open(os.path.join(ROOT, "docs", "step5_data_words.tsv"), encoding="utf-8"), delimiter="\t"):
        if row["lang"] == CODES[lang]:
            k = row["verdict"]
            v = "P" if k.startswith("pointer") else ("Dw" if "weak" in k or "probe only" in k else "D") if k.startswith("data") else "S"
            add(int(row["offset"], 16), "data", v, f"{k}: {row['evidence']}"[:200])

    m = open(os.path.join(ROOT, "build", f"gsmerge_{lang}.gba"), "rb").read()
    d = open(rom, "rb").read()
    res = {}
    for a, ev in out.items():
        relocated = m[0x01000000 + a:0x01000000 + a + 4] != d[a:a + 4]
        res[f"{a:06x}"] = {"value": f"{struct.unpack_from('<I', d, a)[0]:08x}", "relocated": relocated, "ev": ev}
    os.makedirs(os.path.join(ROOT, "build", "step5"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "build", "step5", f"{lang}.json"), "w"), indent=0)
    print(lang, "words with evidence:", len(res), flush=True)


if __name__ == "__main__":
    for lang in sys.argv[1:]:
        collect(lang)
