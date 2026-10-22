"""Boot menu for the merged cartridge: pick Golden Sun or The Lost Age.

Two full-screen Mode 3 images (one per highlighted option) are pre-rendered here; the boot code only copies an
image to VRAM, reads the keypad, selects the flash bank (GS1 -> bank 1, TLA -> bank 0;
bank 1 is always selected once first, which makes emulators switch to a 128 KiB chip), resets RAM via the BIOS
and jumps to the chosen game's entry point.
"""
import os, struct, sys
from PIL import Image, ImageDraw, ImageFont
import asmcache

W, H = 240, 160
FONT_DIR = "C:/Windows/Fonts/"


def _font(name, size):
    return ImageFont.truetype(FONT_DIR + name, size)


def render(selected, items=("Golden Sun", "The Lost Age"), lang="en"):
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):  # dusk gradient
        t = y / (H - 1)
        c = (int(18 + 30 * t), int(22 + 12 * t), int(58 - 20 * t))
        for x in range(W):
            px[x, y] = c
    d = ImageDraw.Draw(img)
    # sun disc behind the title
    d.ellipse((92, 6, 148, 62), fill=(232, 168, 56))
    d.ellipse((100, 14, 140, 54), fill=(248, 208, 96))
    title = _font("georgiab.ttf", 22)
    d.text((W // 2, 40), "GOLDEN SUN", font=title, fill=(255, 244, 214), anchor="mm",
           stroke_width=2, stroke_fill=(70, 30, 10))
    sub = _font("georgia.ttf", 11)
    d.text((W // 2, 62), TEXT[lang]["collection"], font=sub, fill=(232, 200, 140), anchor="mm")

    size = 13      # shrink the option font until the longest entry fits the screen with a margin
    while size > 9 and max(d.textlength(s, font=_font("georgiab.ttf", size)) for s in items) > 216:
        size -= 1
    opt = _font("georgiab.ttf", size)
    half = max(76, int(max(d.textlength(s, font=opt) for s in items)) // 2 + 8)
    top = 92 if len(items) == 2 else 84
    for k, label in enumerate(items):
        y = top + 22 * k
        if k == selected:
            d.rounded_rectangle((W // 2 - half, y - 10, W // 2 + half, y + 10), radius=5, fill=(250, 214, 110),
                                outline=(120, 70, 20))
            d.text((W // 2, y), label, font=opt, fill=(60, 30, 10), anchor="mm")
        else:
            d.text((W // 2, y), label, font=opt, fill=(200, 196, 220), anchor="mm")
    hint = _font("segoeui.ttf", 9)
    d.text((W // 2, 150), TEXT[lang]["hint"], font=hint, fill=(150, 150, 185), anchor="mm")
    return img


def _gold_title(img, xy, text, font, anchor="mm"):
    """Text with a vertical gold gradient fill and a dark-brown outline (like the games' logos)."""
    d = ImageDraw.Draw(img)
    d.text(xy, text, font=font, fill=(70, 30, 10), anchor=anchor, stroke_width=2, stroke_fill=(70, 30, 10))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255, anchor=anchor)
    x0, y0, x1, y1 = mask.getbbox()
    grad = Image.new("RGB", img.size)
    gd = ImageDraw.Draw(grad)
    stops = ((0.0, (255, 252, 220)), (0.45, (255, 214, 96)), (0.55, (232, 150, 40)), (1.0, (255, 200, 90)))
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, y1 - y0)
        for (ta, ca), (tb, cb) in zip(stops, stops[1:]):
            if ta <= t <= tb:
                f = (t - ta) / (tb - ta)
                gd.line((x0, y, x1, y), fill=tuple(int(ca[i] + (cb[i] - ca[i]) * f) for i in range(3)))
                break
    img.paste(grad, (0, 0), mask)


def render_art(bg, selected, items, lang="en"):
    """Start menu over a 240x160 artwork (art/title.png): gold title on the sky, entries on the sea."""
    img = bg.convert("RGB").copy()
    step = 17
    top = H - 12 - step * (len(items) - 1)
    shade = Image.new("L", img.size, 0)                       # soft darkening behind the entries, no box
    sd = ImageDraw.Draw(shade)
    for y in range(top - 18, H):
        sd.line((0, y, W, y), fill=min(120, (y - top + 18) * 6))
    img.paste(Image.new("RGB", img.size, (6, 10, 34)), (0, 0), shade)
    _gold_title(img, (W // 2, 21), "GOLDEN SUN", _font("georgiab.ttf", 25))
    d = ImageDraw.Draw(img)
    d.text((W // 2, 42), TEXT[lang]["collection"], font=_font("georgiab.ttf", 11), fill=(255, 240, 200),
           anchor="mm", stroke_width=2, stroke_fill=(60, 30, 20))

    size = 12
    while size > 9 and max(d.textlength(s, font=_font("georgiab.ttf", size)) for s in items) > 200:
        size -= 1
    opt = _font("georgiab.ttf", size)
    half = max(66, int(max(d.textlength(s, font=opt) for s in items)) // 2 + 8)
    for k, label in enumerate(items):
        y = top + step * k
        if k == selected:
            d.rounded_rectangle((W // 2 - half, y - 8, W // 2 + half, y + 8), radius=4, fill=(250, 214, 110),
                                outline=(120, 70, 20))
            d.text((W // 2, y), label, font=opt, fill=(60, 30, 10), anchor="mm")
        else:
            d.text((W // 2, y), label, font=opt, fill=(236, 234, 248), anchor="mm", stroke_width=2,
                   stroke_fill=(10, 16, 48))
    return img


GS_FRAME = ((82, 82, 82), (255, 255, 255), (165, 165, 165), (0, 0, 0), (0, 82, 82), (0, 90, 99), (0, 99, 115))
GS_FILL = (0, 107, 140)


def gs_window(img, box):
    """A window drawn like the games' own (grey/white/grey/black frame, teal shading, teal fill)."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    for k, c in enumerate(GS_FRAME):
        d.rounded_rectangle((x0 + k, y0 + k, x1 - k, y1 - k), radius=max(0, 3 - k), outline=c)
    d.rectangle((x0 + len(GS_FRAME), y0 + len(GS_FRAME), x1 - len(GS_FRAME), y1 - len(GS_FRAME)), fill=GS_FILL)


def pixel_text(img, xy, text, font, fill=(255, 255, 255), shadow=(16, 16, 16), anchor="lm"):
    """Crisp (not anti-aliased) text with the games' one-pixel drop shadow."""
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    x, y = xy
    d.text((x + 1, y + 1), text, font=font, fill=shadow, anchor=anchor)
    d.text((x, y), text, font=font, fill=fill, anchor=anchor)


LOGO_LAYOUT = {   # logo shift and subtitle anchor ("lm" = left/middle) per source logo
    "tla": {"shift": (0, -6), "sub": (68, 87), "sub_size": 12},   # subtitle where "The Lost Age" was
    "gs1": {"shift": (0, -6), "sub": (32, 100), "sub_size": 13},  # subtitle under the stone plate
}


def render_classic(bg, logo, selected, items, lang="en", kind="tla"):
    """Start menu in the style of the original title screens: generated sky (art/title.png), the real Golden Sun
    logo read from the player's ROM (title_logo.py; TLA's by default), "Collection" as subtitle, game-style window."""
    lay = LOGO_LAYOUT[kind]
    img = bg.convert("RGB").copy()
    img.paste(logo, lay["shift"], logo)
    _gold_title(img, lay["sub"], TEXT[lang]["collection"], _font("georgiab.ttf", lay["sub_size"]), anchor="lm")
    font = _font("verdanab.ttf", 9)
    d = ImageDraw.Draw(img)
    width = max(d.textlength(t, font=font) for t in items)
    row = 12
    x0 = int(W // 2 - width // 2 - 18)
    x1 = int(W // 2 + width // 2 + 14)
    y1 = H - 2
    y0 = y1 - row * len(items) - 12
    gs_window(img, (x0, y0, x1, y1))
    for k, label in enumerate(items):
        y = y0 + 9 + row * k
        tx = x0 + 15
        if k == selected:
            d.polygon(((x0 + 7, y - 3), (x0 + 11, y), (x0 + 7, y + 3)), fill=(255, 214, 66), outline=(16, 16, 16))
            pixel_text(img, (tx, y), label, font, fill=(255, 230, 120))
        else:
            pixel_text(img, (tx, y), label, font, fill=(255, 255, 255))
    return img


CARD_BG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "art", "card_bg.png")
CARD_BG_PROMPT = (   # MOSS-Image, seed 2, 960x640 (tools/comfy_gen.moss_workflow); generated, not from the games
    "Soft hand-painted pre-rendered background art from a Game Boy Advance fantasy RPG title screen (Golden Sun: "
    "The Lost Age, Camelot, 2002), airy and luminous, smooth painterly gradients, strong atmospheric perspective, "
    "no hard outlines. A vast view over a wide green-blue valley and a calm shining sea under a bright pale blue sky "
    "with large soft white and lavender clouds. Layered hazy blue mountain ridges recede into the mist. Far away in "
    "the middle of the valley a tall slender ancient stone lighthouse tower stands in pale blue haze. A small "
    "sailing ship with white sails on the distant sea. Sunlight glows softly from the top of the picture. The "
    "centre is open, calm and uncluttered. Bright, peaceful, adventurous fantasy atmosphere. No characters, no "
    "text, no logo.")
CARD_BG_NEGATIVE = ("nsfw, worst quality, blurry, photograph, 3d render, dark, night, text, letters, logo, watermark, "
                    "signature, jpeg artifact")


def render_chapter_card(lang="en"):
    """Valley background (art/card_bg.png) with the chapter texts; dark outlines keep them readable on the sky."""
    img = Image.open(CARD_BG).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((W // 2, 80), TEXT[lang]["chapter2"], font=_font("georgiab.ttf", 14), fill=(255, 214, 120), anchor="mm",
           stroke_width=2, stroke_fill=(70, 30, 10))
    d.text((W // 2, 104), TEXT[lang]["tla"], font=_font("georgiab.ttf", 22 if len(TEXT[lang]["tla"]) < 16 else 17), fill=(255, 244, 214), anchor="mm",
           stroke_width=2, stroke_fill=(70, 30, 10))
    d.text((W // 2, 138), TEXT[lang]["continues"], font=_font("georgia.ttf", 10), fill=(255, 255, 255),
           anchor="mm", stroke_width=2, stroke_fill=(24, 40, 90))
    return img


def card_bg_generate(out, seeds):
    """Developers: candidate card backgrounds with MOSS-Image in a local ComfyUI."""
    import comfy_gen
    os.makedirs(out, exist_ok=True)
    for s in seeds:
        p = os.path.join(out, f"seed{s}.png")
        comfy_gen.run(None, s, 0, 0, p, comfy_gen.moss_workflow(CARD_BG_PROMPT, CARD_BG_NEGATIVE, s, 960, 640))
        print(p, flush=True)


def card_bg_pick(src):
    """Shrink a generated candidate to the screen (15-bit colour, Mode 3) and store it as art/card_bg.png."""
    im = Image.open(src).convert("RGB").resize((W, H), Image.LANCZOS)
    im.point(lambda v: (v >> 3) << 3).save(CARD_BG)


def to_bgr555(img):
    out = bytearray()
    for y in range(H):
        for x in range(W):
            r, g, b = img.getpixel((x, y))
            out += struct.pack("<H", (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10))
    return bytes(out)


THUMB_SRC = """
    ldr r0, =0x04000000
    ldr r1, =0x0403
    strh r1, [r0]
    movs r4, #0
    bl draw
    ldr r0, =0x04000130
    ldrh r5, [r0]
    mvns r5, r5
loop:
    bl vsync
    ldr r0, =0x04000130
    ldrh r1, [r0]
    mvns r1, r1
    mov r2, r1
    bics r2, r5
    mov r5, r1
    movs r3, #0xC0
    tst r2, r3
    bne toggle
    movs r3, #0x09
    tst r2, r3
    bne start
    b loop
toggle:
    movs r3, #1
    eors r4, r3
    bl draw
    b loop
start:
    ldr r0, =0x04000000
    movs r1, #0x80
    strh r1, [r0]
    movs r6, #1
    bl bank
    movs r6, #1
    eors r6, r4
    bl bank
    movs r0, #0xFF
    svc #0x01
    cmp r4, #0
    bne tla
    ldr r0, =GS1_ENTRY
    bx r0
tla:
    ldr r0, =TLA_ENTRY
    bx r0
bank:
    ldr r0, =0x0E005555
    ldr r1, =0x0E002AAA
    movs r2, #0xAA
    strb r2, [r0]
    movs r2, #0x55
    strb r2, [r1]
    movs r2, #0xB0
    strb r2, [r0]
    ldr r3, =0x0E000000
    strb r6, [r3]
    bx lr
draw:
    push {r4, lr}
    ldr r0, =IMG0
    cmp r4, #0
    beq draw_go
    ldr r0, =IMG1
draw_go:
    ldr r1, =0x06000000
    ldr r2, =19200
    svc #0x0C
    pop {r4, pc}
vsync:
    ldr r0, =0x04000006
vs1:
    ldrh r1, [r0]
    cmp r1, #160
    bne vs1
vs2:
    ldrh r1, [r0]
    cmp r1, #160
    beq vs2
    bx lr
"""


def build(base, gs1_entry, tla_entry):
    """Return (blob, entry_address). `base` is the ROM address the blob is placed at."""
    img0, img1 = to_bgr555(render(0)), to_bgr555(render(1))
    head = asmcache.assemble("arm", "add r0, pc, #1\nbx r0", base)
    assert len(head) == 8
    # images go after the code; reserve 0x400 bytes for code + pools
    img0_addr = base + 0x400
    img1_addr = img0_addr + len(img0)
    src = (THUMB_SRC.replace("GS1_ENTRY", hex(gs1_entry)).replace("TLA_ENTRY", hex(tla_entry))
           .replace("IMG0", hex(img0_addr)).replace("IMG1", hex(img1_addr)))
    code = asmcache.assemble("thumb", src, base + 8)
    code = head + bytes(code)
    assert len(code) <= 0x400, len(code)
    blob = code + bytes(0x400 - len(code)) + img0 + img1
    return blob, base


def arm_branch(frm, to):
    return 0xEA000000 | (((to - frm - 8) >> 2) & 0xFFFFFF)




TEXT = {   # all player-visible text of the start menu and chapter card, per language
    "en": {"collection": "Collection", "hint": "Up/Down: choose     A: start", "continue": "Continue",
           "ch1": "Chapter 1 · Golden Sun", "ch2": "Chapter 2 · The Lost Age", "chapter2": "Chapter 2",
           "tla": "The Lost Age", "continues": "Your journey continues..."},
    "de": {"collection": "Sammlung", "hint": "Hoch/Runter: wählen     A: starten", "continue": "Fortsetzen",
           "ch1": "Kapitel 1 · Golden Sun", "ch2": "Kapitel 2 · Die vergessene Epoche",
           "chapter2": "Kapitel 2", "tla": "Die vergessene Epoche", "continues": "Deine Reise geht weiter..."},
    "fr": {"collection": "Collection", "hint": "Haut/Bas : choisir     A : lancer", "continue": "Continuer",
           "ch1": "Chapitre 1 · Golden Sun", "ch2": "Chapitre 2 · L'Âge Perdu", "chapter2": "Chapitre 2",
           "tla": "L'Âge Perdu", "continues": "Votre voyage continue..."},
    "it": {"collection": "Collezione", "hint": "Su/Giù: scegli     A: avvia", "continue": "Continua",
           "ch1": "Capitolo 1 · Golden Sun", "ch2": "Capitolo 2 · L'Era Perduta", "chapter2": "Capitolo 2",
           "tla": "L'Era Perduta", "continues": "Il tuo viaggio continua..."},
    "es": {"collection": "Colección", "hint": "Arriba/Abajo: elegir     A: empezar", "continue": "Continuar",
           "ch1": "Capítulo 1 · Golden Sun", "ch2": "Capítulo 2 · La Edad Perdida", "chapter2": "Capítulo 2",
           "tla": "La Edad Perdida", "continues": "Tu viaje continúa..."},
}


def menu_images(lang="en", logo=None):
    """5 raw BGR555 screens in the order runtime.c expects (with Continue x3, without x2).

    logo: RGBA Golden Sun logo cut from the player's ROM (title_logo.logo). With logo + art/title.png the menu
    looks like the original title screens; art only -> render_art; neither -> plain gradient menu.
    """
    t = TEXT[lang]
    with_continue = (t["continue"], t["ch1"], t["ch2"])
    new_game = (t["ch1"], t["ch2"])
    art = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "art", "title.png")
    if os.path.exists(art):        # generated title artwork (see art/README.md)
        bg = Image.open(art).convert("RGB")
        if logo is not None:
            draw = lambda k, items: render_classic(bg, logo, k, items, lang)
        else:
            draw = lambda k, items: render_art(bg, k, items, lang)
    else:
        draw = lambda k, items: render(k, items, lang)
    imgs = [draw(k, with_continue) for k in range(3)] + [draw(k, new_game) for k in range(2)]
    return b"".join(to_bgr555(i) for i in imgs)


def boot_stub(base, target):
    """ARM code at `base` (reached from the cartridge header) that switches to Thumb and jumps to `target`."""
    code = asmcache.assemble("arm", f"ldr r0, [pc, #0]; bx r0; .word {target | 1:#x}", base)
    return bytes(code)


# --- panning start menu (runtime.c boot_main, Mode 0) ------------------------------------------------------
WIN_ROW, WIN_ROWS = 13, 7            # window layer covers tile rows 13..19 (y 104..159)


UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "art", "ui")


def _window_states(lang):
    t = TEXT[lang]
    return [(k, (t["continue"], t["ch1"], t["ch2"])) for k in range(3)] + [(k, (t["ch1"], t["ch2"])) for k in range(2)]


def render_ui(lang, kind="tla"):
    """All text images of one language (needs the Windows fonts Georgia/Verdana; developers only):
    card = "Chapter 2" card (RGB 240x160), subtitle = gold "Collection" (RGBA 240x160, alpha 0/255),
    window0..4 = menu window states (RGBA 240x56, the window layer rows)."""
    lay = LOGO_LAYOUT[kind]
    ui = {"card": render_chapter_card(lang)}
    sub = Image.new("RGB", (W, H), (0, 0, 0))
    _gold_title(sub, lay["sub"], TEXT[lang]["collection"], _font("georgiab.ttf", lay["sub_size"]), anchor="lm")
    m = Image.new("L", (W, H), 0)                             # where the subtitle (incl. outline) was drawn
    ImageDraw.Draw(m).text(lay["sub"], TEXT[lang]["collection"], font=_font("georgiab.ttf", lay["sub_size"]),
                           fill=255, anchor="lm", stroke_width=2, stroke_fill=255)
    sub = sub.convert("RGBA")
    sub.putalpha(m.point(lambda a: 255 if a >= 128 else 0))
    ui["subtitle"] = sub
    for k, (sel, items) in enumerate(_window_states(lang)):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_window(im, sel, items)
        ui[f"window{k}"] = im.crop((0, WIN_ROW * 8, W, (WIN_ROW + WIN_ROWS) * 8))
    return ui


def save_ui(lang):
    os.makedirs(os.path.join(UI_DIR, lang), exist_ok=True)
    for name, im in render_ui(lang).items():
        im.save(os.path.join(UI_DIR, lang, name + ".png"))


def load_ui(lang):
    """The pre-rendered text images from art/ui/<lang>/ (so building needs no fonts)."""
    d = os.path.join(UI_DIR, lang)
    if not os.path.isdir(d):
        raise SystemExit(f"no menu texts for language {lang!r} in {d} (developers: python tools/bootmenu.py ui {lang})")
    ui = {}
    for name in ["card", "subtitle"] + [f"window{k}" for k in range(5)]:
        im = Image.open(os.path.join(d, name + ".png"))
        ui[name] = im.convert("RGB") if name == "card" else im.convert("RGBA")
    return ui


def logo_overlay(logo, ui, kind="tla"):
    """RGBA 256x128: the logo at its screen position plus the gold subtitle (becomes 8 sprites of 64x64)."""
    lay = LOGO_LAYOUT[kind]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(logo, (lay["shift"][0], 0), (0, -lay["shift"][1]))
    sub = ui["subtitle"]
    img.paste(sub.convert("RGB"), (0, 0), sub.split()[3])
    out = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
    out.paste(img.crop((0, 0, W, 128)), (0, 0))
    return out


def draw_window(img, selected, items):
    """The game-style menu window at the bottom of a 240x160 image (no anti-aliasing, few exact colours)."""
    font = _font("verdanab.ttf", 9)
    d = ImageDraw.Draw(img)
    width = max(d.textlength(t, font=font) for t in items)
    row = 12
    x0, x1 = int(W // 2 - width // 2 - 18), int(W // 2 + width // 2 + 14)
    y1 = H - 2
    y0 = y1 - row * len(items) - 12
    assert y0 >= WIN_ROW * 8, "menu window taller than its layer"
    gs_window(img, (x0, y0, x1, y1))
    for k, label in enumerate(items):
        y = y0 + 9 + row * k
        if k == selected:
            d.polygon(((x0 + 7, y - 3), (x0 + 11, y), (x0 + 7, y + 3)), fill=(255, 214, 66), outline=(16, 16, 16))
        pixel_text(img, (x0 + 15, y), label, font, fill=(255, 230, 120) if k == selected else (255, 255, 255))


def _bgr(c):
    return (c[0] >> 3) | ((c[1] >> 3) << 5) | ((c[2] >> 3) << 10)


def _tile8(px, x0, y0):
    return bytes(px[x0 + i % 8, y0 + i // 8] for i in range(64))


def menu_data(lang, logo, pano, ui=None):
    """Blob for runtime.c MENU_DATA: header of u32 offsets + palettes + panorama columns + logo sprites + windows.

    logo: RGBA 240x160 (title_logo.logo), pano: RGB (8*N)x160 panorama (panorama.compose),
    ui: text images (load_ui / render_ui)."""
    ui = ui or load_ui(lang)

    # window layer: 4bpp, palette bank 15 (BG palette 240..255), index 0 transparent
    wins, wcols = [], [None]
    for k in range(len(_window_states(lang))):
        strip = ui[f"window{k}"]
        for c in strip.getdata():
            if c[3] and c[:3] not in wcols:
                wcols.append(c[:3])
        wins.append(strip)
    assert len(wcols) <= 16, f"window needs {len(wcols) - 1} colours, max 15"
    wtiles = bytearray()
    for strip in wins:
        px = strip.load()
        for ty in range(WIN_ROWS):
            for tx in range(30):
                idx = [wcols.index(px[tx * 8 + i % 8, ty * 8 + i // 8][:3]) if px[tx * 8 + i % 8, ty * 8 + i // 8][3] else 0
                       for i in range(64)]
                wtiles += bytes(idx[i] | idx[i + 1] << 4 for i in range(0, 64, 2))
    state_bytes = WIN_ROWS * 30 * 32

    # panorama: 239 colours at BG palette 1..239, column-major tiles (20 per 8 px column)
    pw = pano.size[0]
    assert pw % 8 == 0 and pano.size[1] == H
    q = pano.convert("RGB").quantize(colors=239, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    qp = q.getpalette()[:239 * 3]
    shifted = q.point(lambda i: i + 1)
    spx = shifted.load()
    ptiles = b"".join(_tile8(spx, cx * 8, r * 8) for cx in range(pw // 8) for r in range(20))
    bgpal = [0] + [_bgr(qp[3 * i:3 * i + 3]) for i in range(239)]
    bgpal += [0] * (240 - len(bgpal))
    bgpal += [_bgr(c) if c else 0 for c in wcols] + [0] * (16 - len(wcols))

    # logo sprites: 8bpp, OBJ palette 1..255, index 0 transparent; 4x2 sprites of 64x64, 1D tile order
    ov = logo_overlay(logo, ui)
    rgb = Image.new("RGB", ov.size, (0, 0, 0))
    rgb.paste(ov, (0, 0), ov)
    lq = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    lpal = lq.getpalette()[:255 * 3]
    lpx, apx = lq.load(), ov.load()
    obj = Image.new("P", ov.size, 0)
    opx = obj.load()
    for y in range(ov.size[1]):
        for x in range(ov.size[0]):
            if apx[x, y][3] >= 128:
                opx[x, y] = lpx[x, y] + 1
    ltiles = b"".join(_tile8(opx, (k % 4) * 64 + tx * 8, (k // 4) * 64 + ty * 8)
                      for k in range(8) for ty in range(8) for tx in range(8))
    objpal = [0] + [_bgr(lpal[3 * i:3 * i + 3]) for i in range(len(lpal) // 3)]
    objpal += [0] * (256 - len(objpal))
    assert len(ltiles) == 0x8000

    parts = [struct.pack("<256H", *bgpal), ptiles, struct.pack("<256H", *objpal), ltiles, bytes(wtiles)]
    head_len = 9 * 4
    offs, pos = [], (head_len + 31) & ~31
    for p in parts:
        offs.append(pos)
        pos = (pos + len(p) + 31) & ~31
    header = struct.pack("<9I", pw // 8, offs[0], offs[1], offs[2], offs[3], offs[4], state_bytes, WIN_ROW, WIN_ROWS)
    blob = bytearray(pos)
    blob[:len(header)] = header
    for o, p in zip(offs, parts):
        blob[o:o + len(p)] = p
    return bytes(blob)


if __name__ == "__main__" and sys.argv[1:2] == ["ui"]:   # developers: re-render art/ui (needs the fonts)
    for lang in sys.argv[2:] or list(TEXT):
        save_ui(lang)
        print("wrote", os.path.join(UI_DIR, lang))
elif __name__ == "__main__" and sys.argv[1:2] == ["cardbg"]:   # cardbg OUTDIR 1,2,3 | cardbg pick CANDIDATE.png
    if sys.argv[2] == "pick":
        card_bg_pick(sys.argv[3])
    else:
        card_bg_generate(sys.argv[2], [int(v) for v in sys.argv[3].split(",")])
