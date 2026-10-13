"""Start-menu panorama: GS1 intro scene | generated transition | TLA intro scene (720x160).

The two ends are original, logo-free screens taken unchanged from the player's ROMs:
  GS1: the last intro frame before the title logo (Mt. Aleph in violet clouds, sun and lens-flare rings),
       rebuilt by scene_recipe.py from art/gs1_intro_recipe.json (references into the ROM, no pixels).
  TLA: the intro's valley picture (Jupiter Lighthouse; MFT file with 256-colour palette + graphics LZ,
       240x384), rows TLA_ROW..TLA_ROW+159.
Only the 240 px in between are generated (ComfyUI inpainting) and stored in art/panorama_patch.png (RGBA, opaque
only in the middle). The build composes ROM screens + patch, so no original artwork is kept in the project.

  python panorama.py generate OUTDIR [seeds]   (needs ComfyUI; writes candidates)
  python panorama.py pick OUTDIR/seedN.png     (-> art/panorama_patch.png)
"""
import json, os, struct, sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_recipe

W, H = 240, 160
PW = 3 * W                      # panorama width: GS1 | transition | TLA
SCALE = 3                       # generate at 2160x480 (~1 MP), then box-downscale
HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "..", "art")
PATCH = os.path.join(ART, "panorama_patch.png")
GS1_RECIPE = os.path.join(ART, "gs1_intro_recipe.json")
TLA_ROW = 128                   # which 160 rows of TLA's 240x384 valley picture
TLA_VALLEY_BYTES = 1440 * 64    # 240x384, 8bpp tiles

PROMPT = ("A wide seamless panoramic fantasy landscape painting in the soft, slightly blurry airbrushed style of a "
          "2001 Game Boy Advance RPG intro. At the far left edge a dense wall of billowing lavender, violet and "
          "white clouds fills the picture from top to bottom. Moving right, the violet clouds slowly turn whiter, "
          "thin out and open up into a bright, hazy, almost white sky, and below it a steep hazy blue rocky "
          "mountain slope rises from the lower left towards the right edge, with distant pale blue mountains. "
          "One continuous scene with smooth transitions, soft pastel colors, gentle light. No buildings, no towers, "
          "no spires, no sun, no text, no letters, no writing, no logo, no people.")
BLEND = 24                      # generation may softly touch this many original pixels next to the middle


def gs1_scene(gs1_data):
    return scene_recipe.render_recipe(json.load(open(GS1_RECIPE)), gs1_data)


def tla_scene(tla_data):
    ents = scene_recipe.mft(tla_data)
    for i in range(min(len(ents), 200)):
        try:
            tiles = scene_recipe.decode(tla_data, ents, i, "lz", 0x200)
        except Exception:
            continue
        if len(tiles) == TLA_VALLEY_BYTES:
            break
    else:
        raise ValueError("TLA intro valley picture not found")
    s = ents[i]
    pal = []
    for k in range(256):
        c = struct.unpack_from("<H", tla_data, s + 2 * k)[0]
        r, g, b = c & 31, c >> 5 & 31, c >> 10 & 31
        pal.append((r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2))
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            yy = TLA_ROW + y
            t = (yy // 8) * 30 + x // 8
            px[x, y] = pal[tiles[t * 64 + (yy % 8) * 8 + x % 8]]
    return img


def canvas(left, right):
    c = Image.new("RGB", (PW, H), (180, 170, 220))
    c.paste(left, (0, 0))
    c.paste(right, (2 * W, 0))
    return c


def _roms():
    import build_merge
    f1, f2, _ = build_merge.LANGUAGES["en"]
    return (open(os.path.join(build_merge.ROM_DIR, f1), "rb").read(),
            open(os.path.join(build_merge.ROM_DIR, f2), "rb").read())


def generate(out, seeds):
    import comfy_gen
    os.makedirs(out, exist_ok=True)
    g, t = _roms()
    big = canvas(gs1_scene(g), tla_scene(t)).resize((PW * SCALE, H * SCALE), Image.LANCZOS).convert("RGBA")
    alpha = Image.new("L", (PW, H), 255)                          # repaint the middle; soft edges let the
    alpha.paste(0, (W, 0, 2 * W, H))                              # model continue the originals (the final
    for k in range(BLEND):                                        # patch still keeps only the middle)
        v = int(255 * (k + 1) / (BLEND + 1))
        alpha.paste(v, (W - 1 - k, 0, W - k, H))
        alpha.paste(v, (2 * W + k, 0, 2 * W + k + 1, H))
    big.putalpha(alpha.resize(big.size, Image.BILINEAR))
    src = os.path.join(out, "inpaint_src.png")
    big.save(src)
    name = comfy_gen.upload(src)
    for s in seeds:
        p = os.path.join(out, f"seed{s}.png")
        comfy_gen.run(PROMPT, s, 0, 0, p, comfy_gen.inpaint_workflow(PROMPT, s, name))
        print(p, flush=True)


STRIP = 32                      # edge strips used for colour matching
SEAM = 16                       # build-time cross-fade width at each join


def _stats(img):
    px = list(img.get_flattened_data())
    n = len(px)
    mean = [sum(p[k] for p in px) / n for k in range(3)]
    std = [max(1.0, (sum((p[k] - mean[k]) ** 2 for p in px) / n) ** 0.5) for k in range(3)]
    return mean, std


def colour_match(mid, left, right):
    """Shift the middle's colours towards the GS1 edge on its left half and the TLA edge on its right half."""
    ml, sl = _stats(mid.crop((0, 0, STRIP, H)))
    tl, tsl = _stats(left.crop((W - STRIP, 0, W, H)))
    mr, sr = _stats(mid.crop((W - STRIP, 0, W, H)))
    tr, tsr = _stats(right.crop((0, 0, STRIP, H)))
    out = mid.copy()
    px, op = mid.load(), out.load()
    for x in range(W):
        wl = max(0.0, 1 - x / (W / 2))
        wr = max(0.0, (x - W / 2) / (W / 2))
        for y in range(H):
            c = px[x, y]
            a = [(c[k] - ml[k]) / sl[k] * tsl[k] + tl[k] for k in range(3)]
            b = [(c[k] - mr[k]) / sr[k] * tsr[k] + tr[k] for k in range(3)]
            op[x, y] = tuple(max(0, min(255, int(round(c[k] * (1 - wl - wr) + a[k] * wl + b[k] * wr)))) for k in range(3))
    return out


def make_patch(generated, out=PATCH):
    """Keep only the generated middle third, colour-matched to the two original edges."""
    g, t = _roms()
    gen = Image.open(generated).convert("RGB").resize((PW, H), Image.BOX)
    mid = colour_match(gen.crop((W, 0, 2 * W, H)), gs1_scene(g), tla_scene(t))
    patch = Image.new("RGBA", (PW, H), (0, 0, 0, 0))
    patch.paste(mid, (W, 0))
    patch.save(out)
    return out


def _seams(pano):
    """Fade the first/last SEAM columns of the middle towards the neighbouring original's edge colour (per row,
    averaged over 3 rows x 2 columns). Only middle pixels change."""
    px = pano.load()

    def edge(x0, y):
        cs = [px[x, yy] for x in (x0, x0 + (1 if x0 == 2 * W else -1)) for yy in (max(0, y - 1), y, min(H - 1, y + 1))]
        return [sum(c[i] for c in cs) / len(cs) for i in range(3)]

    for y in range(H):
        el, er = edge(W - 1, y), edge(2 * W, y)
        for k in range(SEAM):
            f = ((k + 0.5) / SEAM) ** 0.8                     # 0 at the join -> 1 inside the middle
            for x, e in ((W + k, el), (2 * W - 1 - k, er)):
                b = px[x, y]
                px[x, y] = tuple(int(round(e[i] * (1 - f) + b[i] * f)) for i in range(3))
    return pano


def compose(gs1_data, tla_data, patch=PATCH):
    """Build-time: original GS1 + TLA screens from the ROMs + generated middle -> RGB 720x160."""
    pano = canvas(gs1_scene(gs1_data), tla_scene(tla_data)).convert("RGBA")
    pano.alpha_composite(Image.open(patch).convert("RGBA"))
    return _seams(pano.convert("RGB"))


if __name__ == "__main__":
    if sys.argv[1] == "generate":
        seeds = [int(s) for s in (sys.argv[3] if len(sys.argv) > 3 else "1,2,3,4").split(",")]
        generate(sys.argv[2], seeds)
    elif sys.argv[1] == "pick":
        print(make_patch(sys.argv[2]))
