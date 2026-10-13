"""Replay of Golden Sun's intro (the camera gliding up Mt. Aleph) on the collection's start screen.

Made once from an mGBA recording (bridge `record`: VRAM/palette/OAM/IO every frame, plus a write log of the IO
registers 0x04000010-0x0400005F, because scroll/blend registers are write-only):
  python intro_timeline.py make GS1.gba RECDIR FIRST LAST OUT.json
The timeline stores only references and numbers: every changed 32-byte VRAM block as (MFT file, codec, skip,
offset) into the decoded ROM files, tile maps and OAM entries as numbers, register values, and the palette fade
factor k (palette = (2,0,0) + (base - (2,0,0)) * k / 256, as GS1 does it). No pixel data.

At build time `assemble()` decodes the referenced files from the player's ROM and produces the cartridge blob for
runtime.c (intro_play): header, source data, base palette, op stream.
"""
import json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_recipe

CH = 32
FADE_FROM = (2, 0, 0)
# op stream (little-endian u32 words): [op | len << 8] [dst] [arg]
OP_FRAME, OP_COPY, OP_DATA, OP_REG, OP_FADE, OP_END = 0, 1, 2, 3, 4, 5


def _ld(rec, f, n):
    return open(os.path.join(rec, f"{f:05d}_{n}.bin"), "rb").read()


def _io_log(rec):
    log = {}
    for line in open(os.path.join(rec, "io_writes.log")):
        f, _, _, _, addr, val = line.strip().rstrip(";").split(",")
        log.setdefault(int(f), []).append((int(addr, 16), int(val) & 0xFFFFFFFF))
    return log


def _fade_k(base, pal):
    ch = lambda c: (c & 31, (c >> 5) & 31, (c >> 10) & 31)
    B = [ch(c) for c in struct.unpack("<256H", base[:0x200])]
    P = [ch(c) for c in struct.unpack("<256H", pal[:0x200])]
    for k in range(257):
        if all(FADE_FROM[j] + ((B[i][j] - FADE_FROM[j]) * k >> 8) == P[i][j] for i in range(256) for j in range(3)):
            return k
    return None


def make(rom, rec, first, last, out, base_frame=400):
    data = open(rom, "rb").read()
    ents = scene_recipe.mft(data)
    sources = dict(scene_recipe._all_sources(data, ents))
    keys = list(sources)
    log = _io_log(rec)
    base_pal = _ld(rec, base_frame, "pal")

    def find(chunk, hint):
        if hint is not None:
            k, so = hint
            if sources[keys[k]][so:so + CH] == chunk:
                return hint
        for k, key in enumerate(keys):
            j = sources[key].find(chunk)
            if j >= 0:
                return (k, j)
        return None

    def vram_ops(old, new):
        ops, hint = [], None
        for o in range(0, 0x18000, CH):
            b = new[o:o + CH]
            if old is not None and old[o:o + CH] == b:
                hint = None
                continue
            if not any(b):
                if old is not None:                                   # VRAM is cleared before the replay
                    ops.append(["data", 0x06000000 + o, b.hex()])
                hint = None
                continue
            src = find(b, hint)
            if src is None:
                if 0xF000 <= o < 0x10000:
                    ops.append(["data", 0x06000000 + o, b.hex()])   # BG1/BG2 tile maps (numbers)
                else:
                    skipped.append(o)                                 # BG0 data (BG0 is hidden by WIN0)
                hint = None
                continue
            k, so = src
            last_op = ops[-1] if ops else None
            if last_op and last_op[0] == "copy" and last_op[1] + last_op[4] == 0x06000000 + o and \
                    last_op[2] == k and last_op[3] + last_op[4] == so:
                last_op[4] += CH
            else:
                ops.append(["copy", 0x06000000 + o, k, so, CH])
            hint = (k, so + CH)
        return ops

    frames = []
    prev = None
    k_last = 0
    skipped = []
    for f in range(first, last + 1):
        cur = {n: _ld(rec, f, n) for n in ("vram", "pal", "oam", "io")}
        ops = vram_ops(prev["vram"] if prev else None, cur["vram"])
        oam_old = prev["oam"] if prev else bytes(0x400)
        for i in range(0, 0x400, 8):
            if cur["oam"][i:i + 8] != oam_old[i:i + 8] or prev is None:
                ops.append(["data", 0x07000000 + i, cur["oam"][i:i + 8].hex()])
        io = cur["io"]
        if prev is None or io[0:0x10] != prev["io"][0:0x10] or io[0x48:0x4C] != prev["io"][0x48:0x4C]:
            ops.append(["reg", 0x04000000, struct.unpack_from("<H", io, 0)[0]])      # incl. windows (they switch
            for i in range(4):                                                    # off blending for the sun)
                ops.append(["reg", 0x04000008 + 2 * i, struct.unpack_from("<H", io, 8 + 2 * i)[0]])
            ops.append(["reg", 0x04000048, struct.unpack_from("<H", io, 0x48)[0]])
            ops.append(["reg", 0x0400004A, struct.unpack_from("<H", io, 0x4A)[0]])
        writes = log.get(f + 1, [])
        if prev is None:                                              # start: latest earlier value of each register
            latest = {}
            for g in sorted(log):
                if g <= f + 1:
                    for addr, val in log[g]:
                        latest[addr] = val
            writes = sorted(latest.items())
        for addr, val in writes:                                     # dump N shows the writes of frame N+1
            if 0x04000010 <= addr < 0x04000020:
                ops.append(["reg", addr, val & 0xFFFF])
                ops.append(["reg", addr + 2, val >> 16])
            elif 0x04000040 <= addr < 0x04000048:                    # window positions (write-only)
                ops.append(["reg", addr, val & 0xFFFF])
            elif addr in (0x04000050, 0x04000052, 0x04000054):
                ops.append(["reg", addr, val & 0xFFFF])
                if addr == 0x04000050:
                    ops.append(["reg", addr + 2, val >> 16 & 0xFFFF])
        k = _fade_k(base_pal, cur["pal"])
        if k is None:                                                 # torn palette write: interpolate
            k = k_last
        if prev is None or k != k_last:
            ops.append(["fade", k])
        k_last = k
        frames.append(ops)
        prev = cur
    # fill torn frames: use the mean of neighbours for frames that repeated the previous k
    tl = {"first": first, "last": last, "sources": [list(key) for key in keys], "frames": frames}
    used = sorted({op[2] for fr in frames for op in fr if op[0] == "copy"})
    tl["sources"] = [list(keys[k]) for k in used]
    remap = {k: i for i, k in enumerate(used)}
    for fr in frames:
        for op in fr:
            if op[0] == "copy":
                op[2] = remap[op[2]]
    # base palette as a recipe reference (it is a ROM palette)
    tl["base_pal"] = scene_recipe_pal_refs(base_pal, sources, keys, tl)
    json.dump(tl, open(out, "w"))
    n_ops = sum(len(fr) for fr in frames)
    print(f"frames {first}-{last}: {n_ops} ops, sources {tl['sources']}, skipped BG0 blocks: {len(set(skipped))}")
    return tl


def scene_recipe_pal_refs(pal, sources, keys, tl):
    refs = []
    for o in range(0, 0x400, CH):
        b = pal[o:o + CH]
        for k, key in enumerate(keys):
            j = sources[key].find(b)
            if j >= 0:
                if list(key) not in tl["sources"]:
                    tl["sources"].append(list(key))
                refs.append([o, tl["sources"].index(list(key)), j])
                break
        else:
            assert not any(b), f"palette block {o:#x} not in ROM"
    return refs


def assemble(tl, gs1_data):
    """-> blob: header (8 u32: op offset, base palette offset, n frames, sources offset, 4 reserved),
    source data (decoded files, each 4-aligned), base palette (0x400), op stream."""
    ents = scene_recipe.mft(gs1_data)
    srcs = [scene_recipe.decode(gs1_data, ents, f, codec, skip) for f, codec, skip in tl["sources"]]
    body = bytearray()
    src_off = []
    for s in srcs:
        src_off.append(32 + len(body))
        body += s + bytes(-len(s) % 32)
    pal = bytearray(0x400)
    for o, si, j in tl["base_pal"]:
        pal[o:o + CH] = srcs[si][j:j + CH]
    pal_off = 32 + len(body)
    body += pal
    ops = bytearray()
    for fr in tl["frames"]:
        for op in fr:
            if op[0] == "copy":
                _, dst, si, so, n = op
                ops += struct.pack("<III", OP_COPY | n << 8, dst, src_off[si] + so)
            elif op[0] == "data":
                b = bytes.fromhex(op[2])
                ops += struct.pack("<II", OP_DATA | len(b) << 8, op[1]) + b
            elif op[0] == "reg":
                ops += struct.pack("<III", OP_REG, op[1], op[2])
            elif op[0] == "fade":
                ops += struct.pack("<III", OP_FADE, 0, op[1])
        ops += struct.pack("<III", OP_FRAME, 0, 0)
    ops += struct.pack("<III", OP_END, 0, 0)
    op_off = 32 + len(body)
    head = struct.pack("<8I", op_off, pal_off, len(tl["frames"]), 32, 0, 0, 0, 0)
    return head + bytes(body) + bytes(ops)


if __name__ == "__main__":
    if sys.argv[1] == "make":
        rom, rec, first, last, out = sys.argv[2:7]
        make(rom, rec, int(first), int(last), out)


def simulate(blob):
    """Python model of runtime.c intro_play: yields (vram, pal, oam, io, scroll) after each frame."""
    op_off, pal_off, nframes = struct.unpack_from("<3I", blob, 0)
    base = struct.unpack_from("<512H", blob, pal_off)
    vram, pal, oam, io = bytearray(0x18000), bytearray(0x400), bytearray(0x400), bytearray(0x60)
    p = op_off
    while True:
        w0, dst, arg = struct.unpack_from("<III", blob, p)
        op, n = w0 & 0xFF, w0 >> 8
        if op == OP_END:
            return
        if op == OP_FRAME:
            p += 12
            scroll = {i: (struct.unpack_from("<H", io, 0x10 + 4 * i)[0], struct.unpack_from("<H", io, 0x12 + 4 * i)[0])
                      for i in range(4)}
            yield bytes(vram), bytes(pal), bytes(oam), bytes(io), scroll
            continue
        if op == OP_COPY:
            mem, base_addr = (vram, 0x06000000) if dst < 0x07000000 else (oam, 0x07000000)
            mem[dst - base_addr:dst - base_addr + n] = blob[arg:arg + n]
            p += 12
        elif op == OP_DATA:
            d = blob[p + 8:p + 8 + n]
            if dst >= 0x07000000:
                oam[dst - 0x07000000:dst - 0x07000000 + n] = d
            else:
                vram[dst - 0x06000000:dst - 0x06000000 + n] = d
            p += 8 + n
        elif op == OP_REG:
            struct.pack_into("<H", io, dst - 0x04000000, arg & 0xFFFF)
            p += 12
        elif op == OP_FADE:
            for i in range(512):
                c = base[i]
                ch = [c & 31, (c >> 5) & 31, (c >> 10) & 31]
                v = [FADE_FROM[j] + ((ch[j] - FADE_FROM[j]) * arg >> 8) for j in range(3)]
                struct.pack_into("<H", pal, 2 * i, v[0] | v[1] << 5 | v[2] << 10)
            p += 12
