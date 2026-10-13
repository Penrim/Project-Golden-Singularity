"""Golden Sun compression format 1 encoder (port of compressC1 from Karanum/gs2-randomiser2, MIT).

Returns the stream WITHOUT the leading format byte (prepend b"\\x01")."""


def compress_c1(src):
    src = bytes(src)
    n = len(src)
    dest = bytearray()
    table = {}
    pos = 0

    def add(p):
        if p < n - 1:
            table.setdefault(src[p] | (src[p + 1] << 8), []).append(p)

    while True:
        flag_pos = len(dest)
        dest.append(0)
        mask = 0x80
        while mask:
            if pos >= n:
                dest[flag_pos] |= mask
                dest += b"\x00\x00"
                return bytes(dest)
            best_len = best_off = 0
            if pos < n - 1:
                for p in table.get(src[pos] | (src[pos + 1] << 8), ()):
                    if pos - p > 0xFFF:
                        continue
                    length = 2
                    while pos + length < n and src[pos + length] == src[p + length] and length < 0x10F:
                        length += 1
                    if length >= best_len:
                        best_len, best_off = length, pos - p
            add(pos)
            if best_len < 2:
                dest.append(src[pos]); pos += 1
            else:
                dest[flag_pos] |= mask
                if best_len <= 16:
                    dest.append(((best_off >> 8) << 4) | (best_len - 1))
                    dest.append(best_off & 0xFF)
                else:
                    dest.append((best_off >> 8) << 4)
                    dest.append(best_off & 0xFF)
                    dest.append(best_len - 17)
                end = pos + best_len
                pos += 1
                while pos < end:
                    add(pos); pos += 1
            mask >>= 1


def patch_c1(stream, new_plain):
    """Re-encode a format-1 stream with the SAME token structure but new plaintext bytes.

    `stream` excludes the format byte. Literal tokens take bytes from `new_plain`; back-references are kept.
    Returns (new_stream, bad_positions): bad_positions are plaintext offsets where a kept back-reference now
    produces a byte different from `new_plain` (caller must fall back to recompression for those files)."""
    s = bytearray(stream)
    out = bytearray()
    pos = 0
    p = 0
    while True:
        flags = s[pos]; pos += 1
        mask = 0x80
        while mask:
            if flags & mask == 0:
                s[pos] = new_plain[p]
                out.append(new_plain[p]); p += 1; pos += 1
            else:
                b = s[pos]
                offset = s[pos + 1] | ((b & 0xF0) << 4)
                count = b & 15
                pos += 2
                if count == 0:
                    if offset == 0:
                        bad = [i for i in range(len(new_plain)) if i >= len(out) or out[i] != new_plain[i]]
                        return bytes(s), bad
                    count = s[pos] + 16; pos += 1
                for _ in range(count + 1):
                    out.append(out[len(out) - offset]); p += 1
            mask >>= 1


def patch_c0(stream, new_plain):
    """Like patch_c1 for format 0 (LSB-first bitstream; a literal is a 1 flag bit + 8 data bits).

    Literal data bits are overwritten in place, so the bit structure (and decode timing) is unchanged."""
    s = bytearray(stream)
    nbits = len(s) * 8

    def peek(b, n):
        v = 0
        for k in range(n):
            if b + k < nbits:
                v |= ((s[(b + k) >> 3] >> ((b + k) & 7)) & 1) << k
        return v

    def poke(b, n, v):
        for k in range(n):
            i, sh = (b + k) >> 3, (b + k) & 7
            s[i] = (s[i] & ~(1 << sh)) | (((v >> k) & 1) << sh)

    out = bytearray()
    b = 0
    while True:
        w = peek(b, 16)
        count = 0
        if w & 1:
            poke(b + 1, 8, new_plain[len(out)])
            out.append(new_plain[len(out)])
            b += 9
            continue
        if w & 3 == 0: count, b = 2, b + 2
        elif w & 7 == 2: count, b = 3, b + 3
        elif w & 0xF == 6: count, b = 4, b + 4
        elif w & 0x1F == 0xE: count, b = 5, b + 5
        elif w & 0x7F == 0x1E: count, b = 6, b + 7
        elif w & 0x7F == 0x5E: count, b = 7, b + 7
        elif w & 0x3F == 0x3E:
            count = 7 + ((w >> 6) & 3); b += 8
            if count == 7:
                count = 10 + peek(b, 7); b += 7
                if count == 10:
                    bad = [i for i in range(len(new_plain)) if i >= len(out) or out[i] != new_plain[i]]
                    return bytes(s), bad
        if peek(b, 1) == 0:
            b += 1
            width = 12
            limit = (len(out) - 33) & 0xFFFFFFFF
            while limit < (1 << (width - 1)):
                width -= 1
            offset = 32 + peek(b, width); b += width
        else:
            offset = peek(b + 1, 5); b += 6
        for _ in range(count):
            out.append(out[len(out) - offset - 1])
