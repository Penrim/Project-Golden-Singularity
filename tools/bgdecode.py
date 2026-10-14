"""Input length of GS1's battle-background decoder (ARM routine USA/FR 0x080B9138, 0x230 bytes, copied to RAM).

Fixed output: 15 x 8 x 32 x 8 = 30 720 pixels. Per pixel the low 3 bits of the bit buffer select the code length:
x00 -> 2 bits, 001/101 -> 4, 011/111 -> 6, 010 -> 8, 110 -> 10 (the routine's jump table). The buffer is refilled
16 bits at a time (ldrh) when it runs short. span() returns the offset after the last halfword the routine reads, so
filemap.py can prove that a file is exactly one compressed background.
"""
import struct

PIXELS = 15 * 8 * 32 * 8
BITS = {0: 2, 4: 2, 1: 4, 5: 4, 3: 6, 7: 6, 2: 8, 6: 10}


def span(d, pos):
    """(pixels decoded, end offset); end = position after the last 16-bit read, as in the ARM routine."""
    buf = struct.unpack_from("<H", d, pos)[0]
    pos += 2
    extra = 0                                         # r2: valid bits in the buffer minus 16
    for _ in range(PIXELS):
        n = BITS[buf & 7]
        buf >>= n
        extra -= n
        if extra < 0:
            buf |= struct.unpack_from("<H", d, pos)[0] << (extra + 16)
            pos += 2
            extra += 16
    return PIXELS, pos
