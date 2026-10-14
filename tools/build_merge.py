"""Build the merged cartridge: The Lost Age (unchanged) + Golden Sun relocated to 0x09000000 + start menu.

One cartridge per language: both ROMs must be the same language version. Every version-specific address is
found automatically (tools/profiles.py).

Usage:
  python build_merge.py --lang en|de|fr|it|es             (ROMs from ../work/goldensun/clean, output build/gsmerge_<lang>.gba)
  python build_merge.py GS1.gba TLA.gba out.gba [--lang xx]
"""
import json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom
import build_gs1_reloc
import bootmenu
import title_logo
import panorama
import intro_timeline
import profiles
import transfer_patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROM_DIR = os.path.join(HERE, "..", "..", "work", "goldensun", "clean")
LANGUAGES = {   # language -> (GS1 file, TLA file, expected game codes)
    "en": ("Golden Sun (USA, Europe).gba", "Golden Sun - The Lost Age (USA, Europe).gba", ("AGSE", "AGFE")),
    "de": ("Golden Sun (Germany).gba", "Golden Sun - Die Vergessene Epoche (Germany).gba", ("AGSD", "AGFD")),
    "fr": ("Golden Sun (France).gba", "Golden Sun - L'Age Perdu (France).gba", ("AGSF", "AGFF")),
    "it": ("Golden Sun (Italy).gba", "Golden Sun - L'Era Perduta (Italy).gba", ("AGSI", "AGFI")),
    "es": ("Golden Sun (Spain).gba", "Golden Sun - La Edad Perdida (Spain).gba", ("AGSS", "AGFS")),
}

GS1_BASE = build_gs1_reloc.SHIFT          # file offset of GS1 in the merged ROM
BOOT_BASE = 0x01900000                    # ARM boot stub
TLA_PATCH_BASE = 0x01A00000               # patched TLA files (recompressed map code)
RUNTIME_BASE = 0x01B00000                 # C runtime (cart/runtime.c, linked at 0x09B00000)
CHAPTER_CARD = 0x01B10000                 # 240x160 BGR555 "Chapter 2" image (runtime.c CHAPTER_CARD)
MENU_DATA = 0x01B30000                    # start menu: panorama, logo, windows (runtime.c MENU_DATA)
INTRO_DATA = 0x01C00000                   # GS1 intro replay (runtime.c INTRO_DATA, tools/intro_timeline.py)


def patch_flash(out, base, rom):
    """AgbFlash: let 128 KiB chips use the 64 KiB routines (each game owns one bank) + FLASH1M marker."""
    marker, ids = profiles.find_flash_ids(rom.data)
    for old, new in ((0x1CC2, 0x09C2), (0x1B32, 0x1362)):     # Macronix 512->1M, Panasonic->Sanyo 1M
        off = base + ids[old]
        assert struct.unpack_from("<H", out, off)[0] == old
        struct.pack_into("<H", out, off, new)
    out[base + marker:base + marker + 10] = b"FLASH1M_V1"      # save-type marker (same length as FLASH_V123)


def build(gs1_path, tla_path, out_path, lang="en"):
    g, t = Rom(gs1_path), Rom(tla_path)
    gp, tp = profiles.profile_gs1(gs1_path), profiles.profile_tla(tla_path)
    print(f"{lang}: GS1 {g.code}, TLA {t.code}")
    runtime, syms = transfer_patch.build_runtime(gp, tp)
    out, free = build_gs1_reloc.build(gs1_path, None, profile=gp, mapcode_patch={
        gp["title_mapcode"]: lambda code: transfer_patch.patch_gs1_title(code, gp, syms)})
    assert free <= BOOT_BASE
    out[0:len(t.data)] = t.data
    patch_flash(out, 0, t)
    patch_flash(out, GS1_BASE, g)

    assert syms["tla_receive_gs1"] >> 20 == (0x08000000 + RUNTIME_BASE) >> 20
    assert len(runtime) < CHAPTER_CARD - RUNTIME_BASE
    out[RUNTIME_BASE:RUNTIME_BASE + len(runtime)] = runtime
    ui = bootmenu.load_ui(lang)                    # pre-rendered menu texts (art/ui/<lang>)
    card = bootmenu.to_bgr555(ui["card"])
    out[CHAPTER_CARD:CHAPTER_CARD + len(card)] = card
    title = transfer_patch.patch_tla_title(t.data, tp, syms)
    out[TLA_PATCH_BASE:TLA_PATCH_BASE + len(title)] = title
    struct.pack_into("<I", out, tp["mft_off"] + 4 * tp["title_mapcode"], 0x08000000 + TLA_PATCH_BASE)

    logo = title_logo.logo(t.data, tp["mft_off"], "tla")              # TLA logo from the player's ROM
    pano = panorama.compose(g.data, t.data)        # original intro screens from the ROMs + generated middle
    menu = bootmenu.menu_data(lang, logo, pano, ui)
    out[MENU_DATA:MENU_DATA + len(menu)] = menu
    assert MENU_DATA + len(menu) <= INTRO_DATA
    intro = intro_timeline.assemble(json.load(open(os.path.join(HERE, "..", "art", "gs1_intro_timeline.json"))), g.data)
    assert INTRO_DATA + len(intro) <= len(out)
    out[INTRO_DATA:INTRO_DATA + len(intro)] = intro
    stub = bootmenu.boot_stub(0x08000000 + BOOT_BASE, syms["boot_main"])
    out[BOOT_BASE:BOOT_BASE + len(stub)] = stub
    struct.pack_into("<I", out, 0, bootmenu.arm_branch(0x08000000, 0x08000000 + BOOT_BASE))
    open(out_path, "wb").write(out)
    print(f"wrote {out_path}: {len(out) // 0x100000} MiB")


def main(argv):
    lang = "en"
    if "--lang" in argv:
        i = argv.index("--lang")
        lang = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if lang not in LANGUAGES:
        raise SystemExit(f"unknown language {lang!r}; known: {', '.join(LANGUAGES)}")
    if argv:
        gs1, tla, out = argv[:3]
    else:
        f1, f2, codes = LANGUAGES[lang]
        gs1, tla = os.path.join(ROM_DIR, f1), os.path.join(ROM_DIR, f2)
        out = os.path.join(HERE, "..", "build", f"gsmerge_{lang}.gba")
        assert (Rom(gs1).code, Rom(tla).code) == codes, "ROM language does not match --lang"
    build(gs1, tla, out, lang)


if __name__ == "__main__":
    main(sys.argv[1:])
