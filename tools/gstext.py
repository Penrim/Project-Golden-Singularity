"""Golden Sun text bank: locate the block table and the protected text data range.

Layout (GS1 and TLA): Huffman forest + offset table, a header {forest ptr, offsets ptr}, then per 256-string
block a bitstream followed by a byte length table, and finally the block table {bitstream ptr, lengths ptr}[n].
"""
import struct

ROM = 0x08000000


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def find_text_table(d, start, end):
    """Find the block table: pairs (p, l) where the 256 lengths at l sum to l - p."""
    size = len(d)
    best = None
    for o in range(start & ~3, end - 16, 4):
        n, x, prev = 0, o, 0
        while x + 8 <= size:
            p, l = _u32(d, x), _u32(d, x + 4)
            if not (ROM <= p < l < ROM + size and p > prev):
                break
            if n == 0 and sum(d[l - ROM:l - ROM + 255]) != l - p and sum(d[l - ROM:l - ROM + 256]) != l - p:
                break
            n += 1; prev = l; x += 8
        if n >= 4 and (best is None or n > best[1]):
            best = (o, n)
    return best


def text_layout(d, table_off, nblocks):
    first_bits = _u32(d, table_off) - ROM
    header = first_bits - 8                     # {forest ptr, offsets ptr}
    forest = _u32(d, header) - ROM
    return {
        "table": table_off,
        "blocks": nblocks,
        "header": header,
        "forest": forest,
        "data_start": forest,
        "data_end": table_off,
        "pointers": {header, header + 4} | {table_off + 4 * k for k in range(2 * nblocks)},
    }


# ---------------------------------------------------------------------------------------------------------
# Decoder (port of Karanum/gs2-randomiser2 textutil.js, MIT): one Huffman tree per previous character.
# ---------------------------------------------------------------------------------------------------------
def read_trees(d, forest, offsets):
    """Return 256 trees; a tree node is either ('leaf', char) or ('node', left, right)."""
    trees = []
    for ti in range(256):
        tree_addr = forest + struct.unpack_from("<H", d, offsets + 2 * ti)[0]
        root = {}
        queue = [root]
        off2 = 1          # "offset" in the JS port, doubled to stay integer
        shift = 0
        done = False
        for i in range(64):
            byte = d[tree_addr + i]
            for _ in range(8):
                node = queue.pop()
                if byte & 1:
                    off2 += 1
                    shift += 12
                    char_addr = tree_addr - 3 * (off2 // 2)
                    v = d[char_addr] | (d[char_addr + 1] << 8) | (d[char_addr + 2] << 16)
                    node["char"] = (v >> (shift % 24)) & 0xFFF
                else:
                    node["l"], node["r"] = {}, {}
                    queue.append(node["r"]); queue.append(node["l"])
                byte >>= 1
                if not queue:
                    done = True
                    break
            if done:
                break
        trees.append(root)
    return trees


def string_pointers(d, table, nblocks, limit_end=None):
    """Start offsets (ROM file offsets) of every string: per block a bitstream pointer + byte length table."""
    out = []
    for b in range(nblocks):
        p = struct.unpack_from("<I", d, table + 8 * b)[0] - ROM
        lens = struct.unpack_from("<I", d, table + 8 * b + 4)[0] - ROM
        end = (struct.unpack_from("<I", d, table + 8 * (b + 1))[0] - ROM) if b + 1 < nblocks else None
        k = 0
        for j in range(256):
            if end is not None and p >= lens:
                break
            out.append(p)
            n = 0
            while True:
                byte = d[lens + k]; k += 1
                n += byte
                if byte != 0xFF:
                    break
            p += n
            if b + 1 == nblocks and p >= lens:
                break
    return out


def decode_string(d, trees, addr, max_chars=4000):
    prev, data, out = 0, 1, []
    while len(out) < max_chars:
        node = trees[prev]
        while "char" not in node:
            if data == 1:
                data = 0x100 | d[addr]; addr += 1
            node = node["r"] if data & 1 else node["l"]
            data >>= 1
        prev = node["char"]
        if prev & 0xFF == 0:
            break
        out.append(prev)
    return out


def load_bank(d, table, nblocks):
    first_bits = struct.unpack_from("<I", d, table)[0] - ROM
    forest = struct.unpack_from("<I", d, first_bits - 8)[0] - ROM
    offsets = struct.unpack_from("<I", d, first_bits - 4)[0] - ROM
    trees = read_trees(d, forest, offsets)
    return [decode_string(d, trees, p) for p in string_pointers(d, table, nblocks)]


def pretty(codes):
    return "".join(chr(c) if 32 <= c < 127 else ("ä" if c == 0xE4 else "ö" if c == 0xF6 else "ü" if c == 0xFC
                   else "ß" if c == 0xDF else "Ä" if c == 0xC4 else "Ö" if c == 0xD6 else "Ü" if c == 0xDC
                   else "{%x}" % c) for c in codes)
