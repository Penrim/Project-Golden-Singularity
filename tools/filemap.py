"""Prove the format of every file in GS1's Master File Table (for the word accounting in wordmap.py).

A file counts as packed when a decoder that starts at a known offset stops exactly at the end of the file
(at most 3 bytes of 4-byte alignment padding after it). Then none of its raw bytes can be a ROM pointer: the game
reads it only through the decoder. Decoders: Golden Sun formats 0/1 (gsfs.decompress_span, first byte = format) and
the graphics LZ (gfxlz.decompress_span), each optionally after a palette (0x20, 0x80, 0x1C0, 0x200 bytes), or a table
of u16/u32 offsets at the file start with one packed part per entry (parts may be padded to the next entry).
file_spans() returns the proven sections of every file: header/palette, packed parts, and padding (only zero bytes).

  python filemap.py GS1.gba          (summary + the files that are not proven packed)
"""
import collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom, decompress_span
import gfxlz
import bgdecode
import nibbledecode

PREFIXES = (0, 0x20, 0x80, 0x1C0, 0x200)


def _try(fn, d, pos, end):
    """Decoded length if the decoder stops at the file end (at most 3 bytes of padding before it, or one byte
    beyond it: format 0 fetches its bit stream 16 bits at a time and may prefetch one byte past its end marker)."""
    try:
        out, stop = fn(d, pos)
    except (IndexError, ValueError, KeyError):
        return None
    if end - 3 <= stop <= end + 1 and len(out) > 0:
        return len(out)
    return None


def _decoders(d, pos, end):
    """Try both decoders at pos; returns (name, length) if one stops exactly at end (<= 3 bytes padding)."""
    if d[pos] in (0, 1):
        n = _try(decompress_span, d, pos, end)
        if n:
            return f"gs{d[pos]}", n
    n = _try(gfxlz.decompress_span, d, pos, end)
    return ("lz", n) if n else None


def _padding_ok(d, lo, hi):
    """Bytes between the end of a packed part and the next part: accepted when no 4-aligned word in them looks
    like a ROM pointer (they cannot need relocation then)."""
    for a in range((lo + 3) & ~3, hi - 3, 4):
        if 0x08 == d[a + 3] and struct.unpack_from("<I", d, a)[0] < 0x08000000 + len(d):
            return False
    return True


def offset_table(d, s, end):
    """Files that start with a table of u32 or u16 offsets (relative to the file start); the first offset is the
    table size. Proven when every part decodes and stops at or before the next part, the bytes in between holding
    no pointer-like word. Returns (description, spans) or None."""
    for width, fmt in ((4, "<I"), (2, "<H")):
        first = struct.unpack_from(fmt, d, s)[0]
        if not (width * 2 <= first < end - s) or first % width:
            continue
        offs = [struct.unpack_from(fmt, d, s + k)[0] for k in range(0, first, width)]
        if any(b < a for a, b in zip(offs, offs[1:])) or offs[-1] >= end - s:
            continue
        bounds = sorted(set(offs)) + [end - s]
        spans, names = [(s, s + first, f"u{width * 8} offset table")], []
        for a, b in zip(bounds, bounds[1:]):
            r = _decode_upto(d, s + a, s + b)
            if not r:
                names = None; break
            names.append(r[0])
            spans.append((s + a, r[1], f"packed part ({r[0]})"))
            spans.append((r[1], s + b, "padding"))
        if names:
            return f"u{width * 8} offset table, {len(offs)} parts ({'/'.join(sorted(set(names)))})", spans
    return None


def header_offsets(d, s, end):
    """Battle/sprite files (loaded by the routine at USA 0x0800F338 as file 296 + table value): header with u32
    file offsets: +0x24, +0x28, +0x2C = GS-packed parts, +0x30, +0x34 = optional GS-packed parts (0 = none),
    +0x38 = a part used unpacked (its address is stored for later reads). Proven when every packed part decodes and
    the parts, ordered by offset, follow each other with at most padding in between (no pointer-like word there)."""
    size = end - s
    o = [struct.unpack_from("<I", d, s + 0x24 + 4 * k)[0] for k in range(6)]
    packed = o[:3] + [x for x in o[3:5] if x]
    raw = o[5]
    if not all(0x3C <= x < size for x in packed + [raw]) or len(set(packed + [raw])) != len(packed) + 1:
        return None
    for a in range(s, s + 0x3C, 4):                  # the header itself must hold no pointer-like word
        if not _padding_ok(d, a, a + 4):
            return None
    spans = [(s, s + 0x3C, "header (bytes + part offsets)")]
    order = sorted(packed + [raw]) + [size]
    for a, b in zip(order, order[1:]):
        if a == raw:
            spans.append((s + a, s + b, "unpacked part (used directly)"))
            continue
        r = _decode_upto(d, s + a, s + b)
        if not r:
            return None
        spans += [(s + a, r[1], f"packed part ({r[0]})"), (r[1], s + b, "padding")]
    return f"battle header, {len(packed)} packed parts + 1 direct part", spans


def battle_background(d, s, end):
    """Battle backgrounds (files 29-62 in all versions, loaded by the routine at FR 0x080C4904): a 128-colour
    palette (0x100 bytes, bit 15 clear) and the bit stream of the background decoder (bgdecode.py) that ends
    exactly at the file end (the routine's last refill reads at most one halfword beyond)."""
    if end - s <= 0x100 or any(struct.unpack_from("<H", d, s + k)[0] & 0x8000 for k in range(0, 0x100, 2)):
        return None
    try:
        _, stop = bgdecode.span(d, s + 0x100)
    except struct.error:
        return None
    if not end <= stop <= end + 2:
        return None
    return "battle background", [(s, s + 0x100, "palette/header"), (s + 0x100, end, "packed (battle background)")]


def nibble_records(d, s, end):
    """File 240 (portraits, loaded by FR 0x08019432): a u16 offset table indexed by character (0 = unused); each
    record is a 0x20-byte header and a stream of the nibble decoder (nibbledecode.py) that ends exactly where the
    next record starts."""
    first = struct.unpack_from("<H", d, s)[0]
    if not (4 <= first < end - s) or first % 2:
        return None
    offs = sorted({struct.unpack_from("<H", d, s + k)[0] for k in range(0, first, 2)} - {0})
    if not offs or offs[0] < first or offs[-1] + 0x20 >= end - s:
        return None
    spans, bounds = [(s, s + first, "u16 offset table")], offs + [end - s]
    if bounds[0] > first and not _padding_ok(d, s + first, s + bounds[0]):
        return None
    for a, b in zip(bounds, bounds[1:]):
        try:
            _, stop = nibbledecode.span(d, s + a + 0x20)
        except (ValueError, struct.error):
            return None
        if stop != s + b or not _padding_ok(d, s + a, s + a + 0x20):
            return None
        spans += [(s + a, s + a + 0x20, "palette/header"), (s + a + 0x20, s + b, "packed (nibble records)")]
    return f"{len(offs)} nibble-coded records", spans


def _decode_upto(d, pos, nxt):
    """(decoder name, stop) when a decoder at pos stops at or before nxt and the gap holds no pointer-like word."""
    for name, fn in (("gs", decompress_span), ("lz", gfxlz.decompress_span)):
        if name == "gs" and d[pos] not in (0, 1):
            continue
        try:
            out, stop = fn(d, pos)
        except (IndexError, ValueError, KeyError):
            continue
        if out and stop <= nxt + 1 and _padding_ok(d, stop, nxt):
            return name, min(stop, nxt)
    return None


def file_kinds(rom):
    """{file index: (kind, detail)}; kind 'packed' (proven), 'empty', 'dup' (same start as another) or 'unknown'."""
    d = rom.data
    starts = sorted(set(rom.entries))
    nxt = {s: (starts[i + 1] if i + 1 < len(starts) else len(d)) for i, s in enumerate(starts)}
    out, seen = {}, {}
    spans = file_kinds.spans = {}
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
        if kind is None:
            t = offset_table(d, s, end) or header_offsets(d, s, end) or battle_background(d, s, end) or nibble_records(d, s, end)
            if t:
                kind = ("packed", t[0])
                spans[i] = t[1]
        elif kind[0] == "packed" and i not in spans:
            pre = int(kind[1].split("+")[1].split()[0], 16)
            spans[i] = ([(s, s + pre, "palette/header")] if pre else []) + [(s + pre, end, "packed (" + kind[1] + ")")]
        out[i] = kind or ("unknown", f"{end - s} bytes, starts {d[s:s + 8].hex()}")
    return out


def file_spans(rom):
    """{file index: [(lo, hi, label)]} for every file whose layout is proven (see file_kinds)."""
    file_kinds(rom)
    return dict(file_kinds.spans)


if __name__ == "__main__":
    r = Rom(sys.argv[1])
    k = file_kinds(r)
    print(collections.Counter(v[0] for v in k.values()))
    for i, (kind, det) in sorted(k.items()):
        if kind == "unknown":
            print(f"  file {i:4d} @{r.entries[i]:06x}: {det}")
