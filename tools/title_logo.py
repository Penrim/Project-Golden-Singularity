"""Cut the "Golden Sun" logo out of the original title pictures in the player's own ROMs.

Both games keep their title picture as one MFT file (file 22 in the USA and German ROMs; found by shape):
  GS1: 256-colour palette (0x200 bytes) + graphics-LZ stream (gfxlz.py)          -> 600 8bpp tiles
  TLA: 224-colour palette (0x1C0 bytes) + Golden Sun format 0/1 stream (gsfs.py) -> 600 8bpp tiles
The tiles are in reading order (30x20) = one 240x160 picture with logo and background baked together.
The logo is separated by colour (warm/dark vs. sky) and connected shapes. For TLA the subtitle ("The Lost Age" /
"Die vergessene Epoche") and the TM sign are removed so the collection can put its own subtitle there.
Nothing of the original pictures is stored in this project: the build reads them from the ROMs.
"""
import colorsys, os, struct, sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gfxlz
import gsfs

TITLE_BYTES = 600 * 64
GAMES = {"gs1": (0x200, gfxlz.decompress), "tla": (0x1C0, gsfs.decompress)}


def _mft(data, mft_off):
    out, o = [], mft_off
    while True:
        w = struct.unpack_from("<I", data, o)[0]
        if not 0x08000000 <= w < 0x08000000 + len(data):
            return out
        out.append(w - 0x08000000)
        o += 4


def find_title_file(data, mft_off, game):
    pal_bytes, dec = GAMES[game]
    for s in _mft(data, mft_off)[:400]:
        try:
            if len(dec(data[:s + pal_bytes + 0x10000], s + pal_bytes)) == TITLE_BYTES:
                return s
        except (IndexError, ValueError, KeyError):
            pass
    raise ValueError(f"{game} title picture not found")


def title_picture(data, mft_off, game):
    pal_bytes, dec = GAMES[game]
    s = find_title_file(data, mft_off, game)
    pal = []
    for i in range(256):
        c = struct.unpack_from("<H", data, s + 2 * i)[0] if 2 * i < pal_bytes else 0
        r, g, b = c & 31, c >> 5 & 31, c >> 10 & 31
        pal.append((r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2))
    tiles = dec(data, s + pal_bytes)
    img = Image.new("RGB", (240, 160))
    px = img.load()
    for t in range(600):
        tx, ty = t % 30, t // 30
        for k in range(64):
            px[tx * 8 + k % 8, ty * 8 + k // 8] = pal[tiles[t * 64 + k]]
    return img


def _components(sel, diagonal):
    steps = ((1, 0), (-1, 0), (0, 1), (0, -1)) + (((1, 1), (-1, -1), (1, -1), (-1, 1)) if diagonal else ())
    seen, comps = set(), []
    for p in sorted(sel):
        if p in seen:
            continue
        comp, stack = [], [p]
        seen.add(p)
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for dx, dy in steps:
                q = (x + dx, y + dy)
                if q in sel and q not in seen:
                    seen.add(q)
                    stack.append(q)
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def _hsv(c):
    return colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)


def gs1_logo(pic):
    px = pic.load()
    sel = set()
    for y in range(130):
        for x in range(240):
            r, g, b = px[x, y]
            h, s, v = _hsv(px[x, y])
            if (r > b + 12 and s > 0.18) or v < 0.28:
                sel.add((x, y))
    keep = set(_components(sel, False)[0])          # largest shape = the logo (drops "TM" and stray pixels)
    for y in range(160):                             # fill enclosed holes
        xs = [x for x in range(240) if (x, y) in keep]
        for x in range(xs[0], xs[-1] + 1) if len(xs) > 1 else ():
            if (x, y) not in keep and _enclosed(keep, x, y):
                keep.add((x, y))
    return keep


def _tla_select(pic):
    px = pic.load()
    sel = set()
    for y in range(140):
        for x in range(240):
            r, g, b = px[x, y]
            h, s, v = _hsv(px[x, y])
            if (r > b + 6 and s > 0.08) or (v < 0.3 and b <= r + 8):
                sel.add((x, y))
    return _components(sel, True)


def logo_area(pic):
    """Everything belonging to TLA's logo incl. subtitle and TM (for masking it out of the background)."""
    comps = _tla_select(pic)
    return {p for c in comps if len(c) >= 3 and max(y for x, y in c) < 125 for p in c}


def tla_logo(pic):
    px = pic.load()
    comps = _tla_select(pic)
    keep = set(comps[0])                              # ring + "Golden Sun" + most of the ornament
    small = [c for c in comps[1:] if len(c) >= 3]

    def box(c):
        xs, ys = [x for x, y in c], [y for x, y in c]
        return min(xs), min(ys), max(xs), max(ys)

    def whitish(c):
        return sum(_hsv(px[p])[2] for p in c) / len(c) > 0.8 and sum(_hsv(px[p])[1] for p in c) / len(c) < 0.2

    small = [c for c in small if not whitish(c)]      # bright sky specks, not part of the logo
    # Subtitle ("The Lost Age", "L'Age Perdu", two lines in German/Spanish) under "Golden Sun". Shapes right of
    # the ring's ornament (x >= 78) are subtitle letters; further left, letters and ornament overlap in position,
    # so a shape there counts as subtitle when nearly all its pixels have the letters' colours (letters >= 0.93,
    # ornament <= 0.67 in all five language versions).
    in_area = lambda b: 60 <= b[0] and b[2] <= 200 and 75 <= b[1] and b[3] <= 120
    sub = [c for c in small if box(c)[0] >= 78 and in_area(box(c))]
    colours = {px[p] for c in sub for p in c}
    sub += [c for c in small if box(c)[0] < 78 and in_area(box(c)) and
            sum(px[p] in colours for p in c) >= 0.9 * len(c)]
    for c in small:
        if box(c)[0] > 200 or c in sub:               # TM sign, subtitle
            continue
        keep |= set(c)
    return keep


def _enclosed(shape, x, y):
    """True if the shape exists in all four directions from (x, y) (a hole, not a notch)."""
    return (any((i, y) in shape for i in range(x)) and any((i, y) in shape for i in range(x + 1, 240)) and
            any((x, j) in shape for j in range(y)) and any((x, j) in shape for j in range(y + 1, 160)))


def logo(data, mft_off, game="tla"):
    """RGBA 240x160 image: only the logo pixels (at their original position) are opaque."""
    pic = title_picture(data, mft_off, game)
    keep = (tla_logo if game == "tla" else gs1_logo)(pic)
    px = pic.load()
    out = Image.new("RGBA", pic.size, (0, 0, 0, 0))
    op = out.load()
    for x, y in keep:
        op[x, y] = px[x, y] + (255,)
    return out


if __name__ == "__main__":
    rom, out = sys.argv[1:3]
    d = open(rom, "rb").read()
    import profiles
    game = "gs1" if d[0xAC:0xAF] == b"AGS" else "tla"
    mft = (profiles.profile_gs1 if game == "gs1" else profiles.profile_tla)(rom)["mft_off"]
    logo(d, mft, game).save(out)
