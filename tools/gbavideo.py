"""Render GBA video layers from memory dumps (VRAM 0x18000, palette 0x400, OAM 0x400) to RGBA images.

Text backgrounds (mode 0/1, 4bpp/8bpp, all map sizes) and regular (non-affine) sprites. Palette index 0 = transparent.
"""
import struct
from PIL import Image

OBJ_SIZES = {(0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
             (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
             (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64)}


def colour(pal, i):
    c = struct.unpack_from("<H", pal, 2 * i)[0]
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2, 255)


def _tile_pixels(vram, base, tile, bpp8):
    if bpp8:
        o = base + tile * 64
        return list(vram[o:o + 64])
    o = base + tile * 32
    out = []
    for b in vram[o:o + 32]:
        out += [b & 15, b >> 4]
    return out


def render_bg(vram, pal, bgcnt):
    """Whole background map (256..512 px square/rect) as an RGBA image."""
    char = ((bgcnt >> 2) & 3) * 0x4000
    screen = ((bgcnt >> 8) & 31) * 0x800
    bpp8 = bool(bgcnt & 0x80)
    size = bgcnt >> 14
    tw, th = (32, 32) if size == 0 else (64, 32) if size == 1 else (32, 64) if size == 2 else (64, 64)
    img = Image.new("RGBA", (tw * 8, th * 8), (0, 0, 0, 0))
    px = img.load()
    for ty in range(th):
        for tx in range(tw):
            block = (tx // 32) + (ty // 32) * (2 if tw == 64 else 1)
            e = struct.unpack_from("<H", vram, screen + block * 0x800 + ((ty % 32) * 32 + tx % 32) * 2)[0]
            pix = _tile_pixels(vram, char, e & 0x3FF, bpp8)
            pb = 0 if bpp8 else (e >> 12) * 16
            for y in range(8):
                for x in range(8):
                    v = pix[(7 - y if e & 0x800 else y) * 8 + (7 - x if e & 0x400 else x)]
                    if v:
                        px[tx * 8 + x, ty * 8 + y] = colour(pal, pb + v)
    return img


def render_obj(vram, pal, oam, dispcnt, which=None):
    """All visible regular sprites on a 240x160 canvas (lowest OAM index on top)."""
    img = Image.new("RGBA", (240 + 128, 160 + 128), (0, 0, 0, 0))     # 64 px margin for clipped sprites
    one_d = bool(dispcnt & 0x40)
    for n in reversed(range(128) if which is None else which):
        a0, a1, a2 = struct.unpack_from("<HHH", oam, n * 8)
        if a0 & 0x300 == 0x200 or a0 & 0x100:        # hidden or affine (not handled)
            continue
        w, h = OBJ_SIZES.get((a0 >> 14, a1 >> 14), (8, 8))
        x0, y0 = a1 & 0x1FF, a0 & 0xFF
        x0 = x0 - 512 if x0 >= 240 else x0
        y0 = y0 - 256 if y0 >= 160 else y0
        bpp8 = bool(a0 & 0x2000)
        tile = a2 & 0x3FF
        pb = 256 + (0 if bpp8 else (a2 >> 12) * 16)
        hf, vf = a1 & 0x1000, a1 & 0x2000
        spr = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sp = spr.load()
        for ty in range(h // 8):
            for tx in range(w // 8):
                step = 2 if bpp8 else 1
                t = tile + (ty * (w // 8) * step if one_d else ty * 32) + tx * step
                pix = _tile_pixels(vram, 0x10000, t if not bpp8 else t // 2, bpp8) if bpp8 else \
                    _tile_pixels(vram, 0x10000, t, False)
                for y in range(8):
                    for x in range(8):
                        v = pix[y * 8 + x]
                        if v:
                            sp[tx * 8 + x, ty * 8 + y] = colour(pal, pb + v)
        if hf:
            spr = spr.transpose(Image.FLIP_LEFT_RIGHT)
        if vf:
            spr = spr.transpose(Image.FLIP_TOP_BOTTOM)
        if -64 < x0 < 240 + 64 - w and -64 < y0 < 160 + 64 - h:
            img.alpha_composite(spr, (x0 + 64, y0 + 64))
    return img.crop((64, 64, 64 + 240, 64 + 160))


def _c15(pal, i):
    c = struct.unpack_from("<H", pal, 2 * i)[0]
    return c & 31, (c >> 5) & 31, (c >> 10) & 31


def _bg_index(vram, bgcnt, x, y):
    """(palette index, 0 = transparent) of a text background pixel at map coordinates x, y."""
    char = ((bgcnt >> 2) & 3) * 0x4000
    screen = ((bgcnt >> 8) & 31) * 0x800
    bpp8 = bool(bgcnt & 0x80)
    size = bgcnt >> 14
    w = 512 if size in (1, 3) else 256
    h = 512 if size in (2, 3) else 256
    x, y = x % w, y % h
    tx, ty = x // 8, y // 8
    block = (tx // 32) + (ty // 32) * (2 if w == 512 else 1)
    e = struct.unpack_from("<H", vram, screen + block * 0x800 + ((ty % 32) * 32 + tx % 32) * 2)[0]
    px, py = x % 8, y % 8
    if e & 0x400: px = 7 - px
    if e & 0x800: py = 7 - py
    t = e & 0x3FF
    if bpp8:
        v = vram[char + t * 64 + py * 8 + px]
        return v
    b = vram[char + t * 32 + py * 4 + px // 2]
    v = (b >> 4) if px & 1 else (b & 15)
    return (e >> 12) * 16 + v if v else 0


def compose_frame(vram, pal, oam, io, scroll):
    """Render one mode-0 frame like the GBA (BG priorities, regular sprites, semi-transparent OBJ alpha blending).

    scroll: {bg: (hofs, vofs)} (the offset registers are write-only, so they are passed in). If WIN0 is on, its
    layer mask (WININ) is applied to the whole screen (window sizes are write-only too).
    Returns an RGB 240x160 image."""
    disp = struct.unpack_from("<H", io, 0)[0]
    if disp & 0x2000:
        disp = (disp & ~0x1F00) | ((io[0x48] & 0x1F) << 8)
    bgcnt = [struct.unpack_from("<H", io, 8 + 2 * i)[0] for i in range(4)]
    bld = struct.unpack_from("<H", io, 0x50)[0]
    eva, evb = io[0x52] & 31, io[0x53] & 31
    second = (bld >> 8) & 0x3F
    bgs = sorted((bgcnt[i] & 3, i) for i in range(4) if disp & (0x100 << i))
    # OBJ layer: top sprite pixel per position (lowest OAM index wins among equal priority)
    objpix = {}
    one_d = bool(disp & 0x40)
    if disp & 0x1000:
        for n in range(127, -1, -1):
            a0, a1, a2 = struct.unpack_from("<HHH", oam, n * 8)
            if a0 & 0x300 == 0x200 or a0 & 0x100:
                continue
            w, h = OBJ_SIZES.get((a0 >> 14, a1 >> 14), (8, 8))
            x0, y0 = a1 & 0x1FF, a0 & 0xFF
            x0 = x0 - 512 if x0 >= 240 else x0
            y0 = y0 - 256 if y0 >= 160 else y0
            bpp8 = bool(a0 & 0x2000)
            semi = (a0 >> 10) & 3 == 1
            prio = (a2 >> 10) & 3
            for sy in range(h):
                yy = y0 + sy
                if not 0 <= yy < 160:
                    continue
                ty = (h - 1 - sy) if a1 & 0x2000 else sy
                for sx in range(w):
                    xx = x0 + sx
                    if not 0 <= xx < 240:
                        continue
                    tx = (w - 1 - sx) if a1 & 0x1000 else sx
                    step = 2 if bpp8 else 1
                    tile = (a2 & 0x3FF) + ((ty // 8) * (w // 8) * step if one_d else (ty // 8) * 32) + (tx // 8) * step
                    if bpp8:
                        v = vram[0x10000 + tile * 32 + (ty % 8) * 8 + tx % 8]
                        idx = 256 + v
                    else:
                        b = vram[0x10000 + tile * 32 + (ty % 8) * 4 + (tx % 8) // 2]
                        v = (b >> 4) if tx & 1 else (b & 15)
                        idx = 256 + (a2 >> 12) * 16 + v
                    if v:
                        old = objpix.get((xx, yy))
                        if old is None or prio <= old[1]:
                            objpix[(xx, yy)] = (idx, prio, semi)
    img = Image.new("RGB", (240, 160))
    px = img.load()
    for y in range(160):
        for x in range(240):
            layers = []
            for prio, i in bgs:
                hofs, vofs = scroll.get(i, (0, 0))
                v = _bg_index(vram, bgcnt[i], x + hofs, y + vofs)
                if v:
                    layers.append((prio, 1 + i, v, i))
            o = objpix.get((x, y))
            if o:
                layers.append((o[1], 0, o[0], 4))
            layers.sort()
            layers.append((9, 9, 0, 5))                       # backdrop
            top = layers[0]
            c = _c15(pal, top[2])
            if top[3] == 4 and o[2] and (second >> layers[1][3]) & 1:
                d = _c15(pal, layers[1][2])
                c = tuple(min(31, (c[k] * eva + d[k] * evb) >> 4) for k in range(3))
            px[x, y] = tuple(v << 3 | v >> 2 for v in c)
    return img
