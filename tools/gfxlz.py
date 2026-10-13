"""Golden Sun graphics LZ decompressor (port of the ARM routine at GS1 ROM 0x08001B70).

Stream: flag byte, MSB first; 0 = literal byte, 1 = back-reference of two bytes b1 b2:
distance = (b1 >> 4) << 8 | b2, length = (b1 & 15) + 1; length nibble 0 -> one more byte n, length n + 17;
distance 0 (with nibble 0) ends the stream. A flag byte of 0 means 8 literal bytes.
"""


def decompress(src, pos=0):
    out = bytearray()
    while True:
        flags = src[pos]; pos += 1
        if flags == 0:
            out += src[pos:pos + 8]; pos += 8
            continue
        for bit in range(7, -1, -1):
            if not flags >> bit & 1:
                out.append(src[pos]); pos += 1
                continue
            b1, b2 = src[pos], src[pos + 1]; pos += 2
            dist = (b1 >> 4) << 8 | b2
            n = b1 & 15
            if n:
                n += 1
            else:
                if dist == 0:
                    return bytes(out)
                n = src[pos] + 17; pos += 1
            for _ in range(n):
                out.append(out[-dist])
