"""Verify every pointer-like word inside GS1's files (after the Master File Table) from what the game does with it.

Inputs: the original GS1 ROM, a file-tour log (filetour.py: get_file / unpack / copy calls with their registers)
and optionally an all-words probe result (pointer_probe.py runall). For every part of a file the game used:
  unpacked   the logged source is decoded with the Python port of the same decoder (gsfs format 0/1 for the
             'unpack-gs' wrappers, graphics LZ for 'unpack-lz'); the bytes from the source to where the decoder
             stops are packed data -> no word in them can be a ROM pointer
  hw-copy    copied to palette RAM / VRAM / OAM -> colours or graphics, never dereferenced
  ram-copy   copied unchanged into work RAM -> a data structure; its words need a further check
Words in no used part are 'not used in the tour' unless the probe saw them read byte/halfword-wise.

  python fileverify.py GS1.gba FILETOUR.log [PROBE_ALL.txt]
"""
import bisect, collections, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom, decompress_span
import filemap, fileflow, gfxlz, profiles, wordmap

ROM, SHIFT = 0x08000000, 0x01000000
HW = {5: "palette", 6: "vram", 7: "oam"}


def gs1_off(addr, size):
    """Merged-cartridge address -> GS1 file offset (None outside GS1's own area)."""
    o = addr - ROM - SHIFT
    return o if 0 <= o < size else None


def verify(orig, log, probe=None):
    r = Rom(orig); d = r.data; size = len(d)
    ff = fileflow.FileFlow(orig)
    gp = profiles.profile_gs1(orig)
    getfile = ff.getfile + ROM + SHIFT
    wrappers = {o + ROM + SHIFT: k for o, k in ff.wrappers.items()}
    mft_end = r.mft_off + 4 * len(r.entries)
    starts = sorted(set(r.entries))
    file_at = {}
    for i, s in enumerate(r.entries):
        file_at.setdefault(s, i)
    end_of = lambda s: starts[bisect.bisect_right(starts, s)] if bisect.bisect_right(starts, s) < len(starts) else size
    which = lambda o: starts[bisect.bisect_right(starts, o) - 1]

    spans = collections.defaultdict(list)          # file start -> [(lo, hi, kind)]
    requested = collections.Counter()
    bad = []
    for line in open(log):
        f = line.split()
        if len(f) != 5:
            continue
        hook, r0, r1, r2, lr = (int(x, 16) for x in f)
        if hook == getfile:
            requested[r0] += 1
        elif hook in wrappers:
            o = gs1_off(r0, size)
            if o is None or o < mft_end:
                continue
            try:
                out, stop = (gfxlz.decompress_span if wrappers[hook] == "unpack-lz" else decompress_span)(d, o)
            except (IndexError, ValueError):
                bad.append((hook, o)); continue
            spans[which(o)].append((o, stop, "unpacked"))
        elif hook == 0x03001388:
            o = gs1_off(r1, size)
            if o is None or o < mft_end:
                continue
            spans[which(o)].append((o, o + r2, "hw-copy" if (r0 >> 24) in HW else "ram-copy"))

    static = filemap.file_spans(r)                 # proven layouts (palette/header + packed parts, offset tables)
    static_by_start = {r.entries[i]: sp for i, sp in static.items()}
    ev = wordmap.load_probe(probe) if probe else {}
    mapcode = {r.entries[i] for i in range(*gp["mapcode"])}
    verdict = {}
    for a in range(mft_end, size - 3, 4):
        w = struct.unpack_from("<I", d, a)[0]
        if not (ROM <= w < ROM + size):
            continue
        s = which(a)
        if s in mapcode:
            verdict[a] = "mapcode (checked separately)"; continue
        kinds = {k for lo, hi, k in spans.get(s, ()) if lo <= a and a + 4 <= hi}
        part = {k for lo, hi, k in spans.get(s, ()) if lo < a + 4 and a < hi}
        if "unpacked" in kinds:
            verdict[a] = "packed data (decoder input)"
        elif "hw-copy" in kinds:
            verdict[a] = "colours/graphics (copied to video hardware)"
        elif "ram-copy" in kinds:
            verdict[a] = "RAM structure (copied unchanged)"
        elif any(lo <= a and a + 4 <= hi for lo, hi, k in static_by_start.get(s, ())):
            lab = next(k for lo, hi, k in static_by_start[s] if lo <= a and a + 4 <= hi)
            verdict[a] = "format proof: " + lab.split(" (")[0]
        elif part:
            verdict[a] = "straddles a part boundary"
        elif a in ev and ev[a][0] and not ev[a][2]:
            verdict[a] = "read byte-wise by the game (probe)"
        else:
            verdict[a] = "not used in the tour"
    return verdict, requested, bad


if __name__ == "__main__":
    v, req, bad = verify(*sys.argv[1:4])
    print(f"files requested in the tour: {len(req)}; decoder failures: {len(bad)}")
    for k, n in collections.Counter(v.values()).most_common():
        print(f"  {k:45s} {n:6d}")
