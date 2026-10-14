# Golden Sun Collection - developer guide

> Players: see the main `README.md` and `BUILDING.md`. This document is for working on the project itself.

A GBA ROM hack that puts **Golden Sun** (GS1) and **Golden Sun: The Lost Age** (TLA) on one 32 MiB cartridge and
joins them into one story:

- a start menu (Continue / Chapter 1 / Chapter 2),
- separate saves for both games (128 KiB flash, one bank per game),
- an automatic chapter change: when GS1's credits end, the game saves the "clear data", shows
  "Chapter 2 – The Lost Age" and starts TLA's new game, which imports your GS1 party automatically
  (cable-transfer quality: levels, stats, Djinn, items, equipment, coins, names and side-quest flags), with no
  password and no transfer questions.

Both games keep 100 % of their own content. TLA runs unchanged at its original address; GS1 is moved to the
upper half of the ROM ("relocated").

> **Legal:** the ROMs and anything built from them must never be shared; see `LEGAL.md`. Players build with
> `build.py` from their own dumps. Work only with dumps of cartridges you own.

---

## Status (2026-10-12)

| Area | State |
|---|---|
| GS1 relocated to 0x09000000 | done; all 201 maps + all 255 enemy groups + final battle + ending + credits tested, 0 errors |
| Boot/start menu | done (C, `cart/runtime.c` `boot_main`) |
| Separate saves (Flash 128K, bank per game) | done, tested (save, reload, no interference) |
| GS1 → TLA chapter transition with automatic party import | done, tested from power-on and with the real credits |
| Real ending, fully scripted | final battle, ending scenes and credits scripted; the one story step "Lalivero → ship departure scene" is **not** scripted (see `docs/TESTING.md`) |
| Languages | done: **one cartridge per language**: English, German, French, Italian, Spanish (`--lang en/de/fr/it/es`) from the official ROMs; all addresses found automatically (`tools/profiles.py`). Japanese is not supported |
| Start screen | done: GS1's original intro with its music (replayed; GS1's own sound engine) -> white flash -> slowly panning panorama from GS1's intro scene to TLA's intro valley (both unchanged, only the middle generated with ComfyUI), TLA logo from the ROM, game-style menu window; see `art/README.md` |
| Release builder | done (`build.py`, double-click launchers) |

Languages: one cartridge per language, built from that language's official GS1 + TLA ROMs (full official
translation, keyboard, logos). A runtime language switch was rejected: two complete language pairs alone would need 48 MiB,
and German uses different string numbering than English (see MODLOG session 9).

---

## Quick start

All commands from this folder (`GoldenSunMerge/`), Git Bash or PowerShell.

**Play the current build:** double-click `PLAYTEST_EN.bat` or `PLAYTEST_DE.bat` (mGBA dev build + background
logger; other languages: `tools/mgba-dev/mGBA.exe --script tools/playtest_watch.lua build/gsmerge_fr.gba`). Keys: arrows,
X = A, Z = B, Enter = Start, Backspace = Select, Tab = fast forward, F1 = load quick save 1.
The demo states `build/gsmerge_en.ss1` / `build/gsmerge_de.ss1` are GS1 right after the credits: press F1 to watch
the chapter change. **Seen a glitch?** Press **L + R + Select** together: screenshot, savestate, video memory and the
screenshots of the last ~10 seconds are saved to `build/reports/` (no need to take a screenshot yourself).

**Build a cartridge** like a player: `python build.py --gs1 GS1.gba --tla TLA.gba` (see `BUILDING.md`).
Developer shortcut (ROMs from `../work/goldensun/clean/`, output `build/gsmerge_<lang>.gba`; with the ARM
toolchain present this recompiles `cart/runtime.c` and refreshes `cart/prebuilt/`, and new assembler snippets are
added to `data/asm_cache.json`):

```
.venv/Scripts/python -I tools/build_merge.py --lang en
.venv/Scripts/python -I tools/build_merge.py --lang de          (likewise fr, it, es)
.venv/Scripts/python -I tools/build_merge.py GS1.gba TLA.gba out.gba --lang en     (explicit files)
```

Both ROMs must be the same language. `tools/profiles.py` finds every version-specific address; for the USA ROMs
`profiles.check_us()` asserts the hand-verified values.

**Run the automated tests** (see `docs/TESTING.md` for details and expected results):

```
.venv/Scripts/python -I tools/maptour.py    "<GS1 rom of that language>" build/gsmerge_en.gba build/tour     # ~3 min
.venv/Scripts/python -I tools/battletour.py "<GS1 rom of that language>" build/gsmerge_en.gba build/tour     # ~20 min
.venv/Scripts/python -I tools/test_saves.py build/gsmerge_en.gba build/tour/saves
.venv/Scripts/python -I tools/test_menu.py  build/gsmerge_en.gba build/tour/menu
```
(German: `build/gsmerge_de.gba`, output folder e.g. `build/tour_de`; likewise fr, it, es.)

The tests open (minimised) mGBA windows and talk to them over TCP port 61337. To run several tests at the same
time (e.g. one per language), give each its own port: `GSMERGE_PORT=61351 .venv/Scripts/python -I tools/...`.

---

## Setting up from scratch

Everything lives in this folder; nothing is installed system-wide.

1. **ROMs** (never in the repo): your own dumps; the developer shortcut expects them extracted to
   `../work/goldensun/clean/` (one folder above the repository). Required:

   | File | Code | SHA-1 |
   |---|---|---|
   | Golden Sun (USA, Europe).gba | AGSE | 5c4695205413df7db52b9a184815a07783999971 |
   | Golden Sun - The Lost Age (USA, Europe).gba | AGFE | b500663220cb9bf56b9f8e8c0c544f1d6fa3a824 |
   | Golden Sun (Germany).gba | AGSD | c23ab91a39434623cf1a999f387d743ade1a22a6 |
   | Golden Sun - Die Vergessene Epoche (Germany).gba | AGFD | 7820b4c7ba9002b0e9be23a6f45a9ab204986438 |
   | Golden Sun (France).gba | AGSF | 42f3b262c16cfc5bde1fa2b25016fb74046de1b3 |
   | Golden Sun - L'Age Perdu (France).gba | AGFF | f14855c0f8c87a95cc52189e8e3b2bd9df186322 |
   | Golden Sun (Italy).gba | AGSI | ca45e04b26b2f040ac63e679a459d21869f5f28d |
   | Golden Sun - L'Era Perduta (Italy).gba | AGFI | 57f1d005666b81645e55412658427e27099c5907 |
   | Golden Sun (Spain).gba | AGSS | de0bdc889594b012cad213ca83707feb81ada28b |
   | Golden Sun - La Edad Perdida (Spain).gba | AGFS | a2e3e80036195343c2713410ac14f4e329e3f40d |

   The US hashes match No-Intro "verified" (checked against mGBA's `nointro.dat`).

2. **Python venv** (Python 3.13): `python -m venv .venv` then
   `.venv/Scripts/python -m pip install -r requirements-dev.txt`
   (pinned: Pillow 12.3.0, capstone 5.0.9 = disassembler, keystone-engine 0.9.2 = assembler for the hooks).
   Always run tools with `.venv/Scripts/python -I` (isolated mode).

3. **mGBA development build** (needs `--script` and Lua watchpoints, which 0.10.5 lacks):
   `https://s3.amazonaws.com/mgba/mGBA-build-latest-win64.7z` → extract to `tools/mgba-dev/`
   (the build used here: 2026-10-08, commit 143adf5). `tools/mgba/` holds the stable 0.10.5 (not needed).

4. **Arm GNU Toolchain 14.2** (compiles `cart/runtime.c`):
   `https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/arm-gnu-toolchain-14.2.rel1-mingw-w64-x86_64-arm-none-eabi.zip`
   → extract so that `tools/armgcc/bin/arm-none-eabi-gcc.exe` exists.

5. 7-Zip (`C:/Program Files/7-Zip/7z.exe`) was used to unpack the archives.
6. Optional, only to regenerate artwork (not needed to build): ComfyUI portable with Z-Image Turbo
   (portable Windows build, start `run_nvidia_gpu.bat`); models and exact settings in `art/README.md`.

---

## Folder layout

```
GoldenSunMerge/
  README.md / BUILDING.md / LEGAL.md / CHANGELOG.md   for players
  build.py             player entry point (finds/checks the ROMs, builds with the precompiled runtime)
  Build (Windows).bat / Build (macOS).command / build-linux.sh   double-click launchers (own .venv, then build.py)
  roms/                players put their ROM files here (ignored by git)
  requirements*.txt    pinned Python packages (players / developers)
  docs/DEVELOPMENT.md  this file
  docs/MODLOG.md       chronological work journal (every finding, dead end and gotcha, newest at the bottom)
  PLAYTEST_EN.bat / PLAYTEST_DE.bat   play a build in mGBA with the stray-read logger
  docs/TECHNICAL.md    technical reference (memory map, formats, every patch and address)
  docs/TESTING.md      test harness, test scripts, debugging workflow
  art/                 generated start-screen artwork (panorama_patch.png) + how it was made (art/README.md)
  cart/runtime.c       C code that runs on the cartridge (start menu, transfer, chapter change)
  cart/link.ld         linker script (code at 0x09B00000, no RAM sections allowed)
  cart/prebuilt/       compiled runtime per ROM version pair (players need no ARM toolchain)
  art/ui/<lang>/       pre-rendered menu texts (players need no fonts; re-render: python tools/bootmenu.py ui)
  data/asm_cache.json  assembled hook snippets (players need no keystone)
  data/reloc_exclude_<code>.txt   data words never to relocate (tools/pointer_probe.py)
  tools/               build, analysis and test scripts (Python + Lua), see below
  data/fnmap_us.json   early GS1->TLA function matching (from the abandoned engine-port idea)
  build/               output: gsmerge.gba, saves, savestates, test screenshots (git-ignored)
  .venv/ tools/mgba* tools/armgcc/   local tools (git-ignored)
```

Main tools (details in `docs/TECHNICAL.md` / `docs/TESTING.md`):

| Script | Purpose |
|---|---|
| `build_merge.py` | builds the cartridge for one language (calls everything below) |
| `profiles.py` | finds all version-specific addresses by code patterns (GS1 + TLA, any language) |
| `build_gs1_reloc.py` | GS1 relocation + map-code handling |
| `reloc.py` | finds every ROM pointer in GS1 (rules, code coverage) |
| `pointer_probe.py` | checks the relocation in the running game; writes `data/reloc_exclude_<code>.txt` (data words wrongly taken for pointers) |
| `m4a.py`, `gstext.py` | pointer walkers for music and text data |
| `gsfs.py`, `compress.py` | Master File Table, Golden Sun compression formats 0/1 (decode, encode, same-structure patch) |
| `transfer_patch.py` | builds `cart/runtime.c`, patches TLA's and GS1's title map code (hooks) |
| `bootmenu.py` | start-menu data (panorama tiles, logo sprites, window states), chapter card, ARM boot stub |
| `intro_timeline.py`, `scene_recipe.py` | GS1 intro replay and single-frame rebuild from ROM references (made from mGBA recordings) |
| `panorama.py` | start-screen panorama: GS1 intro scene + TLA intro valley from the ROMs + generated middle (ComfyUI inpainting) |
| `comfy_gen.py`, `title_art.py` | generate artwork with local ComfyUI (Z-Image Turbo); turn it into a 240x160 GBA image |
| `title_logo.py`, `gfxlz.py`, `gbavideo.py` | cut the Golden Sun logo from the player's ROM (TLA's by default; GS1 graphics-LZ decoder); render GBA video dumps |
| `emu.py`, `bridge.lua` | drive mGBA from Python (keys, memory, screenshots, watchpoints, breakpoints) |
| `maptour.py`, `battletour.py`, `test_saves.py`, `test_menu.py`, `difftest.py` | automated tests |
| `autoplay.py` | screen-state detection (dialogue / menu / field) for scripted play |
| `playtest_watch.lua` | logger used by PLAYTEST_EN.bat / PLAYTEST_DE.bat |
| `findptr.py`, `bisect_reloc.py`, `thumbdis.py`, `mapcode_calls.py`, `fnmatcher.py`, ... | analysis helpers |

---

## How to continue

1. Read this file, then `docs/TECHNICAL.md` (architecture + addresses), then the end of `docs/MODLOG.md`.
2. Rebuild the ROM and run `maptour.py` once to make sure the environment works (expect "0 stray reads").
3. After any change to the relocation or patches: rebuild, run map tour + menu test (+ battle tour for big
   changes), and look at the screenshots. Record findings in `docs/MODLOG.md`.

### Roadmap / open items

1. **"Continue" straight into the save** (skip the game's own title screen).
2. **Close the ending-script gap** (Lalivero → ship departure scene, needs a realistic late-game flag set).
3. Optional: verify on real hardware / flash carts (needs FLASH1M save type).

Adding a language version (done this way for FR/IT/ES): MFT offsets in `gsfs.py` (`MFT_OFFSETS`; GS1 = longest
run of ROM pointers starting with 0x08000000, TLA at 0x680000), the ROM pair in `LANGUAGES` (`build_merge.py`) and
`SUPPORTED`/`PAIRS`/`NAMES` (`build.py`), menu texts in `TEXT` (`bootmenu.py`, then `python tools/bootmenu.py ui
<lang>`), build, check the logo cut-out, run the pointer probe (exclusion list) and the tests. If a pattern in
`profiles.py` fails, that version differs and the pattern needs a look.
