"""Build a test ROM with Golden Sun 1 relocated from 0x08000000 to 0x09000000.

The lower 16 MiB is left empty (except a boot branch), so any pointer we failed to relocate reads garbage
and shows up under a range watchpoint. Map code files (compressed, with ROM pointers inside) are decompressed,
relocated, recompressed and appended after GS1.

Usage: python build_gs1_reloc.py GS1.gba out.gba [extra_relocs.txt]
"""
import bisect, os, struct, sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from gsfs import Rom, decompress
import reloc
import typeflow
from reloc import analyse, literal_targets, is_ptr
from compress import compress_c1, patch_c0, patch_c1
import m4a
import gstext
import profiles

SHIFT = 0x01000000          # GS1 moves +16 MiB
OUT_SIZE = 0x02000000       # 32 MiB
EXTRA_BASE = 0x01800000     # free space after the GS1 block
ROM_LO = 0x08000000


def relocate_blob(blob, size):
    """Relocate ROM pointers inside a decompressed map code blob (literal pools only)."""
    b = bytearray(blob)
    n = 0
    for a in literal_targets(b, 0, len(b)):
        if a % 4 == 0 and a + 4 <= len(b):
            w = struct.unpack_from("<I", b, a)[0]
            if is_ptr(w, size):
                struct.pack_into("<I", b, a, w + SHIFT); n += 1
    return bytes(b), n


def load_exclusions(code):
    """data/reloc_exclude_<game code>.txt: file offsets (hex, one per line, # comments) never to relocate."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", f"reloc_exclude_{code}.txt")
    if not os.path.exists(p):
        return set()
    return {int(l.split()[0], 16) for l in open(p) if l.strip() and not l.startswith("#")}


def classify(g, gp, extra=(), info=None):
    """The set of word offsets in GS1's uncompressed area to relocate (everything except map code files).
    info: optional dict, filled with the sources (rule sets, text layout, music, exclusions) for tools/wordmap.py."""
    parts = {}
    text = gstext.text_layout(g.data, *gp["text_table"])
    relocs, stats = analyse(g, gp["code_end"], protected=[(text["data_start"], text["data_end"])],
                            explicit=text["pointers"], parts=parts)
    music = m4a.all_pointers(g.data, gp["song_table"])
    # A heuristic aligned word that overlaps an unaligned music pointer is track data, not a pointer.
    music_bytes = {o + k for o in music if o % 4 for k in range(4)}
    in_music = {a for a in relocs if any(a + k in music_bytes for k in range(4))}
    # Words the heuristics take for pointers but the game reads byte/halfword-wise (pointer probe, per version).
    excl = load_exclusions(g.code)
    # Heuristic hits inside confirmed instructions are code, not tables: two adjacent instructions such as
    # ldrb r3,[r6,#7]; lsrs r2,r2,#1 (0x085279F3) can look like a pointer run, and +0x01000000 would turn
    # lsrs #1 into lsrs #5 (found by tools/wordmap.py: 5 words in the USA ROM).
    stubs = reloc.stub_targets(g, gp["code_end"])
    code = reloc.strict_code(g.data, stubs, gp["code_end"], parts["roots"] - stubs, parts["runs"] | parts["strided"])
    # Words that confirmed code loads PC-relative stay pointers even inside the coverage (switch jump tables).
    loaded = {((h + 4) & ~3) + (g.data[h] & 0xFF) * 4 for h in code if g.data[h + 1] & 0xF8 == 0x48}
    proven = parts["mft"] | set(text["pointers"]) | loaded
    in_code = {a for a in relocs if (a in code or a + 2 in code) and a not in proven}
    # How the program uses the tables (tools/typeflow.py): a guessed word that code reads as bytes/halfwords is
    # data (e.g. the halfword ID list at 0x0C593C: 0x0837 -> 0x0937); a pointer-like word that code loads and
    # uses as an address is a pointer even if no heuristic caught it.
    flow = typeflow.Flow(g, gp["code_end"], code, stubs).run()
    ptr_ev, data_ev = flow.words()
    size = len(g.data)
    is_ptr_word = lambda a: 0 <= a <= size - 4 and is_ptr(struct.unpack_from("<I", g.data, a)[0], size)
    typed_data = {a for a in data_ev if a in relocs and a not in proven and a not in music and a not in ptr_ev}
    typed_ptr = {a for a in ptr_ev if is_ptr_word(a) and a not in relocs and a not in data_ev and a not in excl
                 and not (text["data_start"] <= a < text["data_end"]) and a < gp["code_end"]}
    # Music sample data (m4a wave data: signed 8-bit PCM) is never a pointer, e.g. f2 f1 f1 f0 ef ef f1 f5 fa 00 04 08
    # at 0x106968. Guessed words touching it are dropped; a format-proven pointer there would mean a wrong range.
    samples = m4a.sample_ranges(g.data, gp["song_table"])
    starts = [lo for lo, _ in samples]
    def in_sample(a):
        i = bisect.bisect_right(starts, a + 3) - 1
        return i >= 0 and a < samples[i][1]
    sure = proven | music | set(ptr_ev) | typed_ptr | set(extra)
    proven_in_samples = {a for a in sure if in_sample(a)}
    in_samples = {a for a in relocs if in_sample(a) and a not in sure}
    relocs = (set(relocs) - in_music - excl - in_code - typed_data - in_samples) | typed_ptr | set(extra) | music
    if info is not None:
        info.update(parts=parts, text=text, music=music, music_overlap=in_music, excluded=excl, stats=stats,
                    code=code, in_code=in_code, typed_ptr=typed_ptr, typed_data=typed_data, ptr_ev=ptr_ev,
                    data_ev=data_ev, samples=samples, in_samples=in_samples, proven_in_samples=proven_in_samples)
    print("analysis:", stats, "music:", len(music), "extra:", len(extra), "excluded:", len(excl), "in code:", len(in_code),
          "typed data:", len(typed_data), "typed pointers:", len(typed_ptr), "samples:", len(samples),
          f"({sum(hi - lo for lo, hi in samples)} bytes, {len(in_samples)} guessed words dropped,"
          f" {len(proven_in_samples)} proven pointers inside)", "total:", len(relocs))
    return relocs


def build(gs1_path, out_path, extra=(), mapcode_patch=None, profile=None):
    """Relocate GS1 by +16 MiB. Version-specific addresses come from `profile` (profiles.profile_gs1)."""
    gp = profile or profiles.profile_gs1(gs1_path)
    g = Rom(gs1_path)
    size = len(g.data)
    relocs = classify(g, gp, extra)

    gs1 = bytearray(g.data)
    for a in relocs:
        w = struct.unpack_from("<I", gs1, a)[0]
        assert ROM_LO <= w < ROM_LO + size, f"{a:#x} holds {w:#x}"
        struct.pack_into("<I", gs1, a, w + SHIFT)

    out = bytearray(OUT_SIZE)
    out[SHIFT:SHIFT + size] = gs1
    # Boot: header copy + branch from 0x08000000 to 0x09000000 (GS1's own header branch is PC-relative).
    out[0:0xC0] = g.data[0:0xC0]
    struct.pack_into("<I", out, 0, 0xEA000000 | (((SHIFT - 8) >> 2) & 0xFFFFFF))

    # Map code: decompress + relocate literal pools. Patch in place when the token structure allows it
    # (identical layout and timing), otherwise recompress (format 1), append, and repoint the MFT entry.
    pos = EXTRA_BASE
    total = inplace = 0
    mapcodes = range(*gp["mapcode"])
    for i in mapcodes:
        start, span = g.file_span(i)
        fmt = g.data[start]
        raw = decompress(g.data, start)
        fixed, n = relocate_blob(raw, size)
        total += n
        if mapcode_patch and i in mapcode_patch:
            fixed = mapcode_patch[i](fixed)
        patched, bad = (patch_c0 if fmt == 0 else patch_c1)(g.data[start + 1:start + span], fixed)
        if not bad and decompress(bytes([fmt]) + patched + bytes(8), 0) == fixed:
            out[SHIFT + start + 1:SHIFT + start + span] = patched
            inplace += 1
            continue
        comp = b"\x01" + compress_c1(fixed)
        assert decompress(comp + bytes(8), 0) == fixed, f"round trip failed for map code {i}"
        out[pos:pos + len(comp)] = comp
        struct.pack_into("<I", out, SHIFT + g.mft_off + 4 * i, 0x08000000 + pos)
        pos = (pos + len(comp) + 3) & ~3
    print(f"map code: {inplace} patched in place, {len(mapcodes) - inplace} recompressed")
    print(f"map code: {total} pointers relocated, extra data ends at {pos:#x}")
    if out_path:
        open(out_path, "wb").write(out)
    return out, pos


if __name__ == "__main__":
    extra = []
    if len(sys.argv) > 3:
        extra = [int(x, 16) for x in open(sys.argv[3]).read().split()]
    build(sys.argv[1], sys.argv[2], extra)
