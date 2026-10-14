"""Input length of GS1's nibble decoder (ARM routine FR 0x08014AD8, 0x278 bytes, copied to RAM; used for the
records of file 240, e.g. portraits).

The routine keeps a move-to-front list of 16 colours in two registers and walks a decision tree on single bits; the
tree's shape depends only on the bits, so the input length can be found without the pixel output. Bits are read
LSB first from 32-bit words with a sentinel bit (ldr + rrx); the stream may start unaligned. Ten 1-bits in a row
after a symbol end the stream (branch to the pop/bx at the routine's end).

Tree (labels = the routine's offsets): L24 after each output pixel, L30 the start.
"""
import struct

# state -> (next state if bit 0, next state if bit 1); "out" = a pixel is written and the walk returns to L24
TREE = {
    "L24": ("L30", "L44"),        # bit 0: the same pixel again, then L30
    "L30": ("out", "L44"),
    "L44": ("LCEC", "L54"),
    "L54": ("LCB4", "L64"),
    "L64": ("out", "LB88"),
    "LB88": ("LB98", "LBC0"),
    "LB98": ("out", "out"),
    "LBC0": ("out", "LBE4"),
    "LBE4": ("LBF4", "LC2C"),
    "LBF4": ("out", "out"),
    "LC2C": ("out", "LC50"),
    "LC50": ("LC60", "LC98"),
    "LC60": ("out", "out"),
    "LC98": ("out", "end"),
    "LCB4": ("out", "out"),
    "LCEC": ("out", "LCFC"),
    "LCFC": ("out", "out"),
}


def span(d, pos, limit=1 << 20):
    """(pixels, end): end = 4-aligned offset after the last 32-bit word the routine loads."""
    word = pos & ~3
    bits, nbits = 0, 0
    skip = (pos & 3) * 8

    def bit():
        nonlocal word, bits, nbits, skip
        if nbits == 0:
            bits = struct.unpack_from("<I", d, word)[0] >> skip
            nbits = 32 - skip
            skip = 0
            word += 4
        b = bits & 1
        bits >>= 1
        nbits -= 1
        return b

    state, pixels = "L30", 0
    while pixels < limit:
        nxt = TREE[state][bit()]
        if nxt == "end":
            return pixels, word
        if nxt == "out":
            pixels += 1
            nxt = "L24"
        elif state == "L24" and nxt == "L30":
            pixels += 1                                   # L2C writes the pixel again before L30
        state = nxt
    raise ValueError("no end code")
