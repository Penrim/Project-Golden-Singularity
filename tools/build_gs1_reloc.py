"""Build a test ROM with Golden Sun 1 relocated from 0x08000000 to 0x09000000.

The lower 16 MiB is left empty (except a boot branch), so any pointer we failed to relocate reads garbage
and shows up under a range watchpoint. Map code files (compressed, with ROM pointers inside) are decompressed,
relocated, recompressed and appended after GS1.

Usage: python build_gs1_reloc.py GS1.gba out.gba [extra_relocs.txt]
"""
import os, struct, sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from gsfs import Rom, decompress
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


def build(gs1_path, out_path, extra=(), mapcode_patch=None, profile=None):
    """Relocate GS1 by +16 MiB. Version-specific addresses come from `profile` (profiles.profile_gs1)."""
    gp = profile or profiles.profile_gs1(gs1_path)
    g = Rom(gs1_path)
    size = len(g.data)
    text = gstext.text_layout(g.data, *gp["text_table"])
    relocs, stats = analyse(g, gp["code_end"], protected=[(text["data_start"], text["data_end"])],
                            explicit=text["pointers"])
    music = m4a.all_pointers(g.data, gp["song_table"])
    # A heuristic aligned word that overlaps an unaligned music pointer is track data, not a pointer.
    music_bytes = {o + k for o in music if o % 4 for k in range(4)}
    relocs = {a for a in relocs if not any(a + k in music_bytes for k in range(4))}
    # Words the heuristics take for pointers but the game reads byte/halfword-wise (pointer probe, per version).
    excl = load_exclusions(g.code)
    relocs = {a for a in relocs if a not in excl}
    relocs = relocs | set(extra) | music
    print("analysis:", stats, "music:", len(music), "extra:", len(extra), "excluded:", len(excl), "total:", len(relocs))

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
