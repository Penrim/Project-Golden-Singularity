"""MP2K (m4a / "Sappy") music data walker: finds every ROM pointer in songs, tracks and voicegroups.

Track streams contain GOTO (0xB2), PATT (0xB3) and REPT (0xB5) commands with unaligned 32-bit pointers,
which a word-aligned pointer scan cannot see.
"""
import struct

ROM = 0x08000000


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _looks_like_header(d, h):
    size = len(d)
    if not (0 <= h < size - 8) or d[h] > 16:
        return False
    vg = _u32(d, h + 4)
    if d[h] and not (ROM <= vg < ROM + size):
        return False
    return all(ROM <= _u32(d, h + 8 + 4 * k) < ROM + size for k in range(d[h]))


def find_table_start(d, inside):
    """Walk backwards from an entry known to be in the song table to the table's first entry."""
    size = len(d)
    o = inside
    while o >= 8:
        w = _u32(d, o - 8)
        if not (ROM <= w < ROM + size and _looks_like_header(d, w - ROM)):
            break
        o -= 8
    return o


def song_headers(d, table_off, max_songs=1024):
    size = len(d)
    out = []
    for k in range(max_songs):
        o = table_off + 8 * k
        w = _u32(d, o)
        if not (ROM <= w < ROM + size):
            break
        out.append((o, w - ROM))
    return out


def track_pointers(d, start, size):
    """Offsets (unaligned) of the 4-byte pointers inside one track stream starting at `start`."""
    out = []
    p = start
    limit = start + 0x10000
    while p < min(limit, size - 5):
        c = d[p]
        if c == 0xB1:                       # FINE
            break
        if c in (0xB2, 0xB3):               # GOTO / PATT + ptr
            w = _u32(d, p + 1)
            if ROM <= w < ROM + size:
                out.append(p + 1)
            p += 5
            if c == 0xB2:
                # GOTO normally ends the stream; a FINE usually follows
                if p < size and d[p] == 0xB1:
                    break
            continue
        if c == 0xB5:                       # REPT count + ptr
            w = _u32(d, p + 2)
            if ROM <= w < ROM + size:
                out.append(p + 2)
            p += 6
            continue
        if c == 0xB9:                       # MEMACC op addr data
            p += 4
            continue
        p += 1
    return out


def voicegroup_pointers(d, vg, size, seen, entries=128):
    """Aligned pointer offsets inside a voicegroup (recursing into drumkits/keysplits)."""
    out = []
    if vg in seen:
        return out
    seen.add(vg)
    for k in range(entries):
        e = vg + 12 * k
        if e + 12 > size:
            break
        t = d[e]
        p1, p2 = _u32(d, e + 4), _u32(d, e + 8)
        ok1 = ROM <= p1 < ROM + size
        if t in (0x00, 0x08, 0x10, 0x18, 0x03, 0x0B):        # DirectSound sample / programmable wave
            if ok1:
                out.append(e + 4)
        elif t == 0x40:                                       # keysplit: subgroup + split table
            if ok1:
                out.append(e + 4)
                out += voicegroup_pointers(d, p1 - ROM, size, seen)
            if ROM <= p2 < ROM + size:
                out.append(e + 8)
        elif t == 0x80:                                       # drumkit: subgroup
            if ok1:
                out.append(e + 4)
                out += voicegroup_pointers(d, p1 - ROM, size, seen)
    return out


def all_pointers(d, table_off):
    size = len(d)
    ptrs = set()
    seen_vg = set()
    for entry, h in song_headers(d, table_off):
        ptrs.add(entry)
        if h + 8 > size:
            continue
        ntracks = d[h]
        vg = _u32(d, h + 4)
        if ROM <= vg < ROM + size:
            ptrs.add(h + 4)
            ptrs.update(voicegroup_pointers(d, vg - ROM, size, seen_vg))
        for k in range(ntracks):
            o = h + 8 + 4 * k
            t = _u32(d, o)
            if ROM <= t < ROM + size:
                ptrs.add(o)
                ptrs.update(track_pointers(d, t - ROM, size))
    return ptrs
