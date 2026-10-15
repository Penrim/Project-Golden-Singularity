"""Turn the collected step-5 verdicts (build/step5/<lang>.json, step5_collect.py) into the build's per-version lists:

  data/reloc_exclude_<code>.txt   words never to relocate: the pointer probe's findings (kept) plus every word with
                                  data evidence (D) and no pointer evidence (P); weak-only evidence is marked "weak"
  data/reloc_include_<code>.txt   pointer-like words with pointer evidence that no rule relocates (missed pointers)

Refuses to write anything if a word has both pointer and data evidence (conflicts must be resolved first).
  python step5_apply.py
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_gs1_reloc

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CODES = {"en": "AGSE", "de": "AGSD", "fr": "AGSF", "it": "AGSI", "es": "AGSS"}
ROMS = {"en": "Golden Sun (USA, Europe).gba", "de": "Golden Sun (Germany).gba", "fr": "Golden Sun (France).gba",
        "it": "Golden Sun (Italy).gba", "es": "Golden Sun (Spain).gba"}


def lists(lang):
    res = json.load(open(os.path.join(ROOT, "build", "step5", f"{lang}.json")))
    excl, incl = {}, {}
    for a, r in res.items():
        vs = {v for s, v, d in r["ev"]}
        P, D, Dw = "P" in vs, bool(vs & {"D", "C"}), "Dw" in vs
        if P and (D or Dw):
            raise SystemExit(f"{lang} {a}: pointer and data evidence - resolve first: {r['ev']}")
        src = sorted({s for s, v, d in r["ev"] if v in ("D", "Dw", "C", "P")})
        if (D or Dw) and r["relocated"]:
            excl[int(a, 16)] = ("weak " if not D else "") + "data: " + ",".join(src)
        elif P and not r["relocated"]:
            incl[int(a, 16)] = "pointer: " + ",".join(src)
    vf = os.path.join(ROOT, "build", "verify", f"{lang}.json")    # verify_all.py (tiling and other later proofs)
    if os.path.exists(vf):
        import contextlib, io, m4a, profiles
        from gsfs import Rom
        rom_path = os.path.join(ROOT, "..", "work", "goldensun", "clean", ROMS[lang])
        gp = profiles.profile_gs1(rom_path)
        g = Rom(rom_path)
        music_bytes = {o + k for o in m4a.all_pointers(g.data, gp["song_table"]) for k in range(4)}
        real = build_gs1_reloc.load_exclusions          # what the rules relocate without any list
        build_gs1_reloc.load_exclusions = lambda code, kind="exclude": set()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                heuristic = build_gs1_reloc.classify(g, gp)
        finally:
            build_gs1_reloc.load_exclusions = real
        for k, (verdict, why) in json.load(open(vf)).items():
            if k.split("|")[0] != "rom":
                continue
            a = int(k.split("|")[1])
            if a >= gp["code_end"] or any(a + j in music_bytes for j in range(4)):
                continue                              # files and music pointers have their own handling
            if verdict == "CONFLICT":
                raise SystemExit(f"{lang} {a:06x}: {why}")
            if verdict == "D" and a in heuristic and a not in excl:
                excl[a] = "data: " + why[:80]
            elif verdict == "P" and a not in heuristic and a not in incl:
                incl[a] = "pointer: " + why[:80]
    return excl, incl


def write(lang):
    code = CODES[lang]
    old = build_gs1_reloc.load_exclusions(code)
    excl, incl = lists(lang)
    lines = [f"# GS1 {code}: words the relocation heuristics take for pointers but that are data. One file offset per",
             "# line (+ evidence). Sources: pointer probe (tools/pointer_probe.py) and the step-5 code/format proofs",
             "# (tools/step5_collect.py: tableproof, singles, dataproof, litproof; 'weak' = data evidence whose table",
             "# bound rests on the next label, with no pointer evidence at all). See docs/TECHNICAL.md."]
    for a in sorted(old | set(excl)):
        lines.append(f"{a:06x}  " + ("probe + " if a in old and a in excl else "") + (excl[a] if a in excl else "probe"))
    open(os.path.join(ROOT, "data", f"reloc_exclude_{code}.txt"), "w").write("\n".join(lines) + "\n")
    old_inc = {}
    p_inc = os.path.join(ROOT, "data", f"reloc_include_{code}.txt")
    if os.path.exists(p_inc):                         # keep earlier findings (they are relocated now)
        old_inc = {int(l.split()[0], 16): l.split(None, 1)[1].strip() if len(l.split(None, 1)) > 1 else ""
                   for l in open(p_inc) if l.strip() and not l.startswith("#")}
    incl = {**old_inc, **incl}
    inc = [f"# GS1 {code}: pointers no relocation rule finds (step-5 proofs). One file offset per line (+ evidence)."]
    inc += [f"{a:06x}  {incl[a]}" for a in sorted(incl)]
    open(os.path.join(ROOT, "data", f"reloc_include_{code}.txt"), "w").write("\n".join(inc) + "\n")
    print(f"{lang}: exclude {len(old | set(excl))} (probe {len(old)}, new {len(set(excl) - old)}), include {len(incl)}")


if __name__ == "__main__":
    for lang in CODES:
        write(lang)
