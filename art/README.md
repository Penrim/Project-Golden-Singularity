# Artwork

The start screen: a slowly panning panorama from Golden Sun's intro (the last frame before the title logo:
Mt. Aleph in violet clouds with the sun and lens-flare rings) to The Lost Age's intro (the valley with the
Jupiter Lighthouse), with TLA's real logo, "Collection" and a menu window drawn like the games' own.
**Both ends are the original screens, unchanged**; only the 240 px in between are generated.
Technical details: `docs/TECHNICAL.md` "Start screen".

| File | What |
|---|---|
| `panorama_patch.png` | RGBA 720x160, opaque only in the middle third: the generated transition (colour-matched to both edges) |
| `gs1_intro_recipe.json` | how to rebuild GS1's last intro frame from the ROM: references (MFT file, codec, offset) for every 32-byte block of VRAM/palette, plus OAM, IO registers, scroll offsets and the two tile maps (tile numbers). No pixel data. |
| `gs1_intro_timeline.json` | replay of GS1's intro (frames 290-567) for the power-on sequence: per frame VRAM block references into the ROM, tile maps / OAM / register values and fade factors (numbers). No pixel data. Made with `tools/intro_timeline.py make` from an mGBA recording. |
| `title.png`, `title_source.png`, `title_v*/` | earlier designs (still pictures; superseded) |

Nothing from the original games is stored here; the builder reads the screens and the logo from the player's ROMs.

## How it was made

- GS1 frame: snapshot of frame 558 in mGBA (`build/art/intro/gs1f_*`), scroll offsets found by matching (BG1 0/5,
  BG2 0/216), `python tools/scene_recipe.py make "<GS1>" build/art/intro/gs1f build/art/intro/gs1f.png
  '{"1": [0, 5], "2": [0, 216]}' art/gs1_intro_recipe.json`. Rebuilt-from-ROM == rebuilt-from-snapshot; the same
  recipe gives an identical picture with the German ROM.
- TLA: intro valley picture = MFT file with palette + graphics LZ, 240x384 (file 25 in USA/DE), rows 128..287.
- Middle: `python tools/panorama.py generate build/art/pano_v6 1,...,8` (ComfyUI, Z-Image Turbo inpainting of
  the middle third at 2160x480; the mask fades 24 px into both originals so the model continues them, but the
  stored patch keeps only the middle), chosen **seed 7**, `python tools/panorama.py pick build/art/pano_v6/seed7.png`
  (colour matching of the middle towards both edges). At build time `panorama.compose` fades the first/last 16
  columns of the middle towards the originals' edge colours; the original screens are never changed.

## Menu texts (`ui/<lang>/`)

The start-menu window, the gold "Collection" subtitle and the "Chapter 2" card are pre-rendered per language
(`python tools/bootmenu.py ui`, needs the Windows fonts Georgia and Verdana) so that building needs no fonts.
