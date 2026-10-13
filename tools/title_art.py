"""Turn a generated artwork into a GBA-native 240x160 background (title / start menu).

pixelize(): crop to 3:2, box-downscale to 240x160 (each GBA pixel = average of its source block), reduce to a
limited palette without dithering (crisp pixel-art look) and snap to the GBA's 15-bit colours.
Usage: python title_art.py SRC.png OUT.png [colours=64]
"""
import sys
from PIL import Image

W, H = 240, 160


def pixelize(src, colours=64):
    img = Image.open(src).convert("RGB") if isinstance(src, str) else src.convert("RGB")
    w, h = img.size
    if w * H > h * W:                      # too wide -> crop the sides
        nw = h * W // H
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:                                  # too tall -> crop the bottom (keep the sky)
        img = img.crop((0, 0, w, w * H // W))
    img = img.resize((W, H), Image.BOX)
    img = img.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    return img.point(lambda v: (v >> 3) << 3 | (v >> 5))      # 5 bits per channel, like the GBA shows it


if __name__ == "__main__":
    src, out = sys.argv[1:3]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    pixelize(src, n).save(out)
