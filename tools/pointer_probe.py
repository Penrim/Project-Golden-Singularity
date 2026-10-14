"""Pointer probe: find words the relocation heuristics wrongly take for ROM pointers, by watching the game.

GS1 is moved by +16 MiB; every word the heuristics (pointer runs, strided struct arrays, near singles) classify as a
pointer gets +0x01000000. In data (byte tables, packed sprite graphics) that changes one byte and shows up as wrong
values or graphics glitches (e.g. the Vale prologue: a garbled frame above Isaac). The probe runs the merged ROM
with one read watchpoint over GS1 (bridge.lua `ptrprobe`) and records for every candidate word:
  narrow = 8/16-bit reads, wide = 32-bit reads, used = a 32-bit read followed (within 96 reads) by a read at the
  address it holds. A real pointer is read 32-bit and used; a word read byte/halfword-wise and not used is data.
Coverage: optional savestates, every map (warp + walk) and every enemy group (forced battle).

  python pointer_probe.py run  MERGED.gba ORIG_GS1.gba OUT.txt [state.ss ...]   (~25 min)
  python pointer_probe.py runall MERGED.gba ORIG_GS1.gba OUT.txt [state.ss ...]
      (every pointer-like word of GS1, relocated or not, incl. files; watches 0x08000000-0x09FFFFFF so that a
       not-relocated word used as an address is seen too; OUT.cov = 256-byte blocks read at all = coverage)
  python pointer_probe.py list ORIG_GS1.gba OUT.txt [OTHER_GS1.gba ...]   -> data/reloc_exclude_<code>.txt
      (OTHER_GS1: versions whose lists exist already; their findings are mapped in by surrounding bytes)

The exclusion file is read by build_gs1_reloc.load_exclusions. Music pointers are never excluded (the m4a engine
reads its own pointers byte-wise by design).
"""
import os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from gsfs import Rom
import m4a, profiles, reloc

HERE = os.path.dirname(os.path.abspath(__file__))
SHIFT = 0x01000000


def candidates(merged, orig_path):
    """Word offsets (< code_end) changed by heuristics or listed in the exclusion file."""
    r = Rom(orig_path)
    d, size, code_end = r.data, len(r.data), r.mft_off
    lits = {a for a in reloc.literal_targets(d, 0, code_end) if a % 4 == 0 and reloc.is_ptr(struct.unpack_from("<I", d, a)[0], size)}
    mft = {r.mft_off + 4 * i for i in range(len(r.entries))}
    import build_gs1_reloc
    excl = build_gs1_reloc.load_exclusions(r.code)
    m = open(merged, "rb").read()
    return [a for a in range(0, code_end, 4)
            if a not in lits and a not in mft and (m[SHIFT + a:SHIFT + a + 4] != d[a:a + 4] or a in excl)]


def all_words(orig_path):
    """Every 4-aligned word of GS1 whose value looks like a GS1 ROM address."""
    d = open(orig_path, "rb").read()
    return [a for a in range(0, len(d) - 3, 4) if reloc.is_ptr(struct.unpack_from("<I", d, a)[0], len(d))]


def run(merged, orig_path, out, states=(), every=False):
    import maptour, battletour
    tag = os.path.splitext(os.path.basename(merged))[0] + ("_all" if every else "")
    lst = os.path.join(os.environ.get("TEMP", "."), f"{tag}_probe_list.txt")   # bridge paths: no spaces
    assert " " not in lst, "TEMP path must not contain spaces"
    words = all_words(orig_path) if every else candidates(merged, orig_path)
    open(lst, "w").write("\n".join("%08x" % (0x09000000 + a) for a in words))
    field = maptour.field_state(merged, os.path.abspath(f"build/{tag}_probe_field.ss"), True)
    world = battletour.worldmap_state(merged, field, os.path.abspath(f"build/{tag}_probe_world.ss"))
    rets = profiles.profile_gs1(orig_path)["encounter_returns"]
    e = Emu.launch(merged); e.sock.settimeout(600)
    t0 = time.time()
    try:
        e.cmd(f"ptrprobe {lst} {0x08000000 if every else 0x09000000} {0x09FFFFFF}")
        for s in states:
            e.load(os.path.abspath(s)); e.wait(600)
        for mp in range(201):
            e.load(field); e.wait(2)
            e.w16(maptour.MAP_VAR, mp); e.w16(maptour.WARP_TRIGGER, 1); e.wait(300)
            for k in ("DOWN", "RIGHT", "UP", "LEFT"):
                e.keys(k); e.wait(20)
            e.keys(); e.wait(20)
        for g in range(1, 256):
            e.load(world); e.wait(2)
            for a in rets:
                e.cmd(f"forceret {a + SHIFT} {g}")
            for k in range(6):
                e.keys("LEFT" if k % 2 else "RIGHT"); e.wait(25)
            e.keys(); e.wait(150)
            for k in range(25):
                e.press("A", hold=4, after=26)
            if g % 50 == 0:
                print("group", g, "%.0fs" % (time.time() - t0), flush=True)
        e.cmd("ptrdump " + os.path.abspath(out))
    finally:
        e.proc.kill()


def exclusion_list(orig_path, probe_txt):
    d = open(orig_path, "rb").read()
    music = set(m4a.all_pointers(d, profiles.profile_gs1(orig_path)["song_table"]))
    out = []
    for line in open(probe_txt):
        a, narrow, wide, used = line.split()
        a, narrow, wide, used = int(a, 16) - 0x09000000, int(narrow), int(wide), int(used)
        w = struct.unpack_from("<I", d, a)[0]
        if 0x08000000 <= w < 0x08800000 and a not in music and narrow > 0 and used * 2 < max(wide, 1):
            out.append(a)
    return sorted(out)


def mapped_exclusions(orig_path, other_roms, ctx=12):
    """Exclusions found in other language versions, located in this ROM by the 12 bytes before and after the word
    (unique 4-aligned match; the word itself may differ). Covers words the probe run did not reach."""
    import build_gs1_reloc
    d = open(orig_path, "rb").read()
    music = set(m4a.all_pointers(d, profiles.profile_gs1(orig_path)["song_table"]))
    out = set()
    for other in other_roms:
        s = open(other, "rb").read()
        for a in build_gs1_reloc.load_exclusions(s[0xAC:0xB0].decode()):
            pre, post = s[a - ctx:a], s[a + 4:a + 4 + ctx]
            hits, i = [], d.find(pre)
            while i >= 0:
                if (i + ctx) % 4 == 0 and d[i + ctx + 4:i + 2 * ctx + 4] == post:
                    hits.append(i + ctx)
                i = d.find(pre, i + 1)
            if len(hits) == 1 and 0x08000000 <= struct.unpack_from("<I", d, hits[0])[0] < 0x08800000 \
                    and hits[0] not in music:
                out.add(hits[0])
    return out


if __name__ == "__main__":
    if sys.argv[1] in ("run", "runall"):
        run(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:], every=sys.argv[1] == "runall")
    elif sys.argv[1] == "list":
        orig, probe, others = sys.argv[2], sys.argv[3], sys.argv[4:]   # others: GS1 ROMs with existing lists
        code = open(orig, "rb").read()[0xAC:0xB0].decode()
        probed = exclusion_list(orig, probe)
        mapped = mapped_exclusions(orig, others) if others else set()
        ex = sorted(set(probed) | mapped)
        p = os.path.join(HERE, "..", "data", f"reloc_exclude_{code}.txt")
        src = f" + findings of {len(others)} other versions mapped by surrounding bytes" if others else ""
        open(p, "w").write(f"# GS1 {code}: words the relocation heuristics take for pointers but the game reads byte/halfword-wise\n"
                           f"# (tools/pointer_probe.py probe run{src}; see docs/TECHNICAL.md). One file offset per line.\n" +
                           "\n".join("%06x" % a for a in ex) + "\n")
        print(f"{len(ex)} words ({len(probed)} probed, {len(mapped)} mapped, {len(mapped - set(probed))} only mapped) ->", p)
