"""Rebuild an original game screen from the player's ROM using a "recipe" (references, no graphics).

A recipe is made once from an emulator snapshot (VRAM, palette, OAM, IO registers): every 32-byte block of
video memory and palette is looked up in the game's MFT files (raw, graphics LZ after a 0x1C0/0x200 palette, or
Golden Sun format 0/1) and stored as (file, codec, skip, offset). Blocks that are zero are stored as zero. Tile
maps of the shown backgrounds (tile numbers the game generates, no pixels) are stored as numbers ("maps");
any other block that is not found makes the recipe fail. OAM, IO registers and scroll offsets are plain
numbers. At build time the referenced files are decoded from the ROM and the frame is rendered with
gbavideo.compose_frame. The recipe file contains no picture data.

  python scene_recipe.py make ROM.gba SNAP_PREFIX SHOT.png SCROLL_JSON OUT.json   (SNAP_PREFIX_vram.bin etc.)
  python scene_recipe.py render ROM.gba RECIPE.json OUT.png
"""
import json, os, struct, sys
from PIL import Image, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbavideo
import gfxlz
import gsfs

CHUNK = 32
CODECS = (("raw", 0), ("lz", 0x200), ("lz", 0x1C0), ("gs", 0), ("gs", 0x200), ("gs", 0x1C0))


def mft(data):
    import profiles   # noqa: F401  (MFT offset by game code)
    off = gsfs.MFT_OFFSETS[data[0xAC:0xB0].decode()]
    out = []
    while True:
        w = struct.unpack_from("<I", data, off)[0]
        if not 0x08000000 <= w < 0x08000000 + len(data):
            return out
        out.append(w - 0x08000000)
        off += 4


def decode(data, ents, file, codec, skip):
    s = ents[file]
    later = [e for e in ents if e > s]
    end = min(later) if later else len(data)
    if codec == "raw":
        return data[s:end]
    if codec == "lz":
        return gfxlz.decompress(data[:s + skip + 0x40000], s + skip)
    return gsfs.decompress(data, s + skip)


def _all_sources(data, ents):
    for i in range(len(ents)):
        for codec, skip in CODECS:
            if codec == "gs" and data[ents[i] + skip] not in (0, 1):
                continue
            try:
                out = decode(data, ents, i, codec, skip)
            except Exception:
                continue
            if 32 <= len(out) <= 0x60000:
                yield (i, codec, skip), out


def make(rom, snap, shot, scroll, out):
    data = open(rom, "rb").read()
    ents = mft(data)
    sources = dict(_all_sources(data, ents))
    mem = {n: open(f"{snap}_{n}.bin", "rb").read() for n in ("vram", "pal", "oam", "io")}
    refs = {"vram": [], "pal": []}
    unresolved = {"vram": [], "pal": []}
    for region in ("vram", "pal"):
        buf = mem[region]
        prev = None
        for o in range(0, len(buf), CHUNK):
            chunk = buf[o:o + CHUNK]
            if not any(chunk):
                prev = None
                continue
            src = None
            if prev and prev[0] in sources:                      # continue the previous run if possible
                k, so = prev
                if sources[k][so + CHUNK:so + 2 * CHUNK] == chunk:
                    src = (k, so + CHUNK)
            if src is None:
                for k, d in sources.items():
                    j = d.find(chunk)
                    if j >= 0:
                        src = (k, j)
                        break
            if src is None:
                unresolved[region].append(o)
                prev = None
                continue
            (f, codec, skip), so = src
            if refs[region] and refs[region][-1][1:] == [f, codec, skip] and \
                    refs[region][-1][0] + refs[region][-1][5] == o and refs[region][-1][4] + refs[region][-1][5] == so:
                refs[region][-1][5] += CHUNK                     # extend run
            else:
                refs[region].append([o, f, codec, skip, so, CHUNK])
            prev = src
    io = mem["io"]
    disp = struct.unpack_from("<H", io, 0)[0]
    map_areas = []
    for i in range(4):
        cnt = struct.unpack_from("<H", io, 8 + 2 * i)[0]
        if disp & (0x100 << i):
            blocks = (1, 2, 2, 4)[cnt >> 14]
            map_areas.append(((cnt >> 8 & 31) * 0x800, (cnt >> 8 & 31) * 0x800 + blocks * 0x800))
    maps = [[o, mem["vram"][o:o + CHUNK].hex()] for o in unresolved["vram"] if any(a <= o < b for a, b in map_areas)]
    rest = [o for o in unresolved["vram"] if not any(a <= o < b for a, b in map_areas)] + unresolved["pal"]
    print("runs:", {k: len(v) for k, v in refs.items()}, "map blocks:", len(maps), "unresolved:", len(rest))
    assert not rest, f"blocks not found in the ROM: {[hex(o) for o in rest[:10]]}"
    recipe = {"scroll": {str(k): v for k, v in scroll.items()}, "oam": mem["oam"].hex(), "io": mem["io"].hex(),
              "vram": refs["vram"], "pal": refs["pal"], "maps": maps}
    # unresolved blocks must not matter for the picture
    ref_img = gbavideo.compose_frame(mem["vram"], mem["pal"], mem["oam"], mem["io"], scroll)
    img = render_recipe(recipe, data)
    diff = ImageChops.difference(img, ref_img).getbbox()
    print("rebuilt from ROM == rebuilt from snapshot:", diff is None, diff)
    if shot:
        d2 = ImageChops.difference(img, Image.open(shot).convert("RGB")).convert("L").point(lambda a: 255 if a else 0)
        print("pixels differing from the emulator screenshot:", sum(1 for a in d2.get_flattened_data() if a))
    json.dump(recipe, open(out, "w"))
    return recipe


def render_recipe(recipe, data):
    ents = mft(data)
    cache = {}
    mem = {"vram": bytearray(0x18000), "pal": bytearray(0x400)}
    for region in ("vram", "pal"):
        for o, f, codec, skip, so, n in recipe[region]:
            key = (f, codec, skip)
            if key not in cache:
                cache[key] = decode(data, ents, f, codec, skip)
            mem[region][o:o + n] = cache[key][so:so + n]
    for o, hexdata in recipe.get("maps", []):
        b = bytes.fromhex(hexdata)
        mem["vram"][o:o + len(b)] = b
    scroll = {int(k): tuple(v) for k, v in recipe["scroll"].items()}
    return gbavideo.compose_frame(bytes(mem["vram"]), bytes(mem["pal"]), bytes.fromhex(recipe["oam"]),
                                  bytes.fromhex(recipe["io"]), scroll)


if __name__ == "__main__":
    if sys.argv[1] == "make":
        rom, snap, shot, scroll, out = sys.argv[2:7]
        make(rom, snap, shot, {int(k): tuple(v) for k, v in json.loads(scroll).items()}, out)
    elif sys.argv[1] == "render":
        rom, rec, out = sys.argv[2:5]
        render_recipe(json.load(open(rec)), open(rom, "rb").read()).save(out)
