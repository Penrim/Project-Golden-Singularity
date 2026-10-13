"""Golden Sun (GS1 / TLA) ROM file system: Master File Table + compression.

Compression formats 0 and 1 are ported from Karanum/gs2-randomiser2
(modules/decompression.js, MIT License, (c) 2024 Karanum).
"""
import struct

ROM_BASE = 0x08000000

# MFT location per ROM game code (offset in file). German versions verified 2026-10-12.
MFT_OFFSETS = {
    "AGSD": 0x31FE00,  # Golden Sun (Germany)
    "AGFD": 0x680000,  # Golden Sun - Die Vergessene Epoche (Germany)
    "AGSE": 0x320000,  # Golden Sun (USA, Europe)
    "AGFE": 0x680000,  # Golden Sun - The Lost Age (USA, Europe)
}


class Rom:
    def __init__(self, path):
        self.path = path
        self.data = open(path, "rb").read()
        self.code = self.data[0xAC:0xB0].decode("ascii")
        self.mft_off = MFT_OFFSETS[self.code]
        self.entries = self._read_mft()

    def _read_mft(self):
        entries = []
        off = self.mft_off
        size = len(self.data)
        while True:
            w = struct.unpack_from("<I", self.data, off)[0]
            if not (ROM_BASE <= w < ROM_BASE + size):
                break
            entries.append(w - ROM_BASE)
            off += 4
        return entries

    def file_span(self, idx):
        """Start offset and an upper bound on size (distance to the next file start)."""
        start = self.entries[idx]
        later = [e for e in self.entries if e > start]
        end = min(later) if later else len(self.data)
        return start, end - start

    def raw(self, idx):
        start, size = self.file_span(idx)
        return self.data[start:start + size]

    def decompressed(self, idx):
        start, _ = self.file_span(idx)
        return decompress(self.data, start)


def decompress(src, pos):
    fmt = src[pos]
    if fmt == 0:
        return _decompress_c0(src, pos + 1)
    if fmt == 1:
        return _decompress_c1(src, pos + 1)
    raise ValueError(f"unsupported compression format {fmt}")


def _decompress_c0(src, pos):
    dest = bytearray()
    bitnum = 0
    bits = src[pos] | (src[pos + 1] << 8)
    pos += 2
    while True:
        count = 0
        if bits & 1:
            dest.append((bits >> 1) & 0xFF)
            bits >>= 9
            bitnum -= 9
        elif bits & 3 == 0:
            count = 2; bits >>= 2; bitnum -= 2
        elif bits & 7 == 2:
            count = 3; bits >>= 3; bitnum -= 3
        elif bits & 0xF == 6:
            count = 4; bits >>= 4; bitnum -= 4
        elif bits & 0x1F == 0xE:
            count = 5; bits >>= 5; bitnum -= 5
        elif bits & 0x7F == 0x1E:
            count = 6; bits >>= 7; bitnum -= 7
        elif bits & 0x7F == 0x5E:
            count = 7; bits >>= 7; bitnum -= 7
        elif bits & 0x3F == 0x3E:
            count = 7 + ((bits >> 6) & 3)
            bits >>= 8; bitnum -= 8
            if count == 7:
                count = 10 + (bits & 0x7F)
                bits >>= 7; bitnum -= 7
                if count == 10:
                    return bytes(dest)
        if bitnum < 0:
            bitnum += 16
            bits += (src[pos] << bitnum) + (src[pos + 1] << (8 + bitnum))
            pos += 2
        if count:
            if bits & 1 == 0:
                bits >>= 1; bitnum -= 1
                width = 12
                limit = (len(dest) - 33) & 0xFFFFFFFF  # unsigned, as in the original
                while limit < (1 << (width - 1)):
                    width -= 1
                offset = 32 + (bits & ((1 << width) - 1))
                bits >>= width; bitnum -= width
            else:
                offset = (bits >> 1) & 31
                bits >>= 6; bitnum -= 6
            if bitnum < 0:
                bitnum += 16
                bits += (src[pos] << bitnum) + (src[pos + 1] << (8 + bitnum))
                pos += 2
            for _ in range(count):
                dest.append(dest[len(dest) - offset - 1])


def _decompress_c1(src, pos):
    dest = bytearray()
    while True:
        flags = src[pos]; pos += 1
        mask = 0x80
        while mask:
            if flags & mask == 0:
                dest.append(src[pos]); pos += 1
            else:
                b = src[pos]
                offset = src[pos + 1] | ((b & 0xF0) << 4)
                count = b & 15
                pos += 2
                if count == 0:
                    if offset == 0:
                        return bytes(dest)
                    count = src[pos] + 16; pos += 1
                for _ in range(count + 1):
                    dest.append(dest[len(dest) - offset])
            mask >>= 1
