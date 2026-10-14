"""Prove the format of every file in GS1's Master File Table (for the word accounting in wordmap.py).

A file counts as packed when a decoder that starts at a known offset stops exactly at the end of the file
(at most 3 bytes of 4-byte alignment padding after it). Then none of its raw bytes can be a ROM pointer: the game
reads it only through the decoder. Decoders: Golden Sun formats 0/1 (gsfs.decompress_span, first byte = format) and
the graphics LZ (gfxlz.decompress_span), each optionally after a palette (0x20, 0x1C0, 0x200 bytes).

  python filemap.py GS1.gba          (summary + the files that are not proven packed)
"""
import collections, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom, decompress_span
import gfxlz

PREFIXES = (0, 0x20, 0x1C0, 0x200)


def _try(fn, d, pos, end):
    try:
        out, stop = fn(d, pos)
    except (IndexError, ValueError, KeyError):
        return None
    if end - 3 <= stop <= end and len(out) > 0:
        return len(out)
    return None


def file_kinds(rom):
    """{file index: (kind, detail)}; kind 'packed' (proven), 'empty', 'dup' (same start as another) or 'unknown'."""
    d = rom.data
    starts = sorted(set(rom.entries))
    nxt = {s: (starts[i + 1] if i + 1 < len(starts) else len(d)) for i, s in enumerate(starts)}
    out, seen = {}, {}
    for i, s in enumerate(rom.entries):
        if s in seen:
            out[i] = ("dup", seen[s]); continue
        seen[s] = i
        end = nxt[s]
        if end - s == 0:
            out[i] = ("empty", 0); continue
        kind = None
        for pre in PREFIXES:
            if s + pre >= end:
                continue
            if d[s + pre] in (0, 1):
                n = _try(decompress_span, d, s + pre, end)
                if n:
                    kind = ("packed", f"gs{d[s + pre]}+{pre:#x} -> {n} bytes"); break
            n = _try(gfxlz.decompress_span, d, s + pre, end)
            if n:
                kind = ("packed", f"gfxlz+{pre:#x} -> {n} bytes"); break
        out[i] = kind or ("unknown", f"{end - s} bytes, starts {d[s:s + 8].hex()}")
    return out


if __name__ == "__main__":
    r = Rom(sys.argv[1])
    k = file_kinds(r)
    print(collections.Counter(v[0] for v in k.values()))
    for i, (kind, det) in sorted(k.items()):
        if kind == "unknown":
            print(f"  file {i:4d} @{r.entries[i]:06x}: {det}")
