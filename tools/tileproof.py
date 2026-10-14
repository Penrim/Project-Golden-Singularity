"""Format proof for pointer tables whose targets are packed streams that tile seamlessly.

For every run of >= 2 pointer-like words with ascending targets (program area), try each known decoder on the
targets: the stream at entry i must end where entry i+1 starts (word decoders read whole 32-bit words, so the next
start may lie inside the last word read: 0..3 bytes before the end). When every pair tiles, the table words are
proven pointers (the decoders are run on them: see the loader routines in docs/TECHNICAL.md) and the stream bytes are
proven data.

Decoders: nibbledecode (move-to-front nibble coder; table USA 0x029EE4, loader 0x0801A5A4), Golden Sun formats 0/1
(gsfs, first byte = format), graphics LZ (gfxlz), battle background stream (bgdecode).

  python tileproof.py GS1.gba
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom, decompress_span
import bgdecode, gfxlz, nibbledecode, profiles

ROM = 0x08000000


def _nibble(d, a):
    return nibbledecode.span(d, a)[1], 3


def _gs(d, a):
    if d[a] not in (0, 1):
        raise ValueError
    return decompress_span(d, a)[1], 1


def _lz(d, a):
    return gfxlz.decompress_span(d, a)[1], 0


def _bg(d, a):
    return bgdecode.span(d, a)[1], 2


DECODERS = (("nibble", _nibble), ("gs", _gs), ("lz", _lz), ("bg", _bg))


def tiles(d, targets, fn):
    """True if the stream at every target ends at the next distinct target (within the decoder's read-ahead)."""
    t = sorted(set(targets))
    for a, b in zip(t, t[1:]):
        try:
            stop, ahead = fn(d, a)
        except (ValueError, IndexError, KeyError, struct.error):
            return False
        if not b <= stop <= b + ahead:
            return False
    return len(t) >= 2


def proofs(path):
    """({table word: (decoder, table start)}, {stream word: (decoder, table start)})."""
    g = Rom(path)
    d, size = g.data, len(g.data)
    end = profiles.profile_gs1(path)["code_end"]
    is_ptr = lambda w: ROM <= w < ROM + size
    ptr_words, data_words = {}, {}
    a = 0
    while a < end - 4:
        if not is_ptr(struct.unpack_from("<I", d, a)[0]):
            a += 4; continue
        run = []
        b = a
        while b < end - 3 and is_ptr(struct.unpack_from("<I", d, b)[0]):
            run.append(b); b += 4
        vals = [struct.unpack_from("<I", d, x)[0] - ROM for x in run]
        if len(run) >= 2 and all(v2 >= v1 for v1, v2 in zip(vals, vals[1:])):
            for name, fn in DECODERS:
                if tiles(d, vals, fn):
                    t = sorted(set(vals))
                    try:                              # the last stream must decode as well
                        last_end, _ = fn(d, t[-1])
                    except (ValueError, IndexError, KeyError, struct.error):
                        continue
                    for x in run:
                        ptr_words[x] = (name, a)
                    for w in range((t[0] + 3) & ~3, min(last_end, size) - 3, 4):
                        if w not in ptr_words:
                            data_words[w] = (name, a)
                    break
        a = b
    return ptr_words, data_words


if __name__ == "__main__":
    p, dw = proofs(sys.argv[1])
    tabs = sorted({(n, t) for n, t in p.values()})
    print("tables proven by tiling:", len(tabs), "table words:", len(p), "stream words:", len(dw))
    for n, t in tabs:
        print(f"  {t:06x} {n:7s} {sum(1 for v in p.values() if v == (n, t))} entries")
