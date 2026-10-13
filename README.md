# Golden Sun Collection

**Golden Sun** and **Golden Sun: The Lost Age** on one Game Boy Advance cartridge, joined into one continuous
story. A fan-made ROM hack for your own legally dumped cartridges.

> **No game files are included or distributed here.** You build the cartridge yourself from your own dumps of
> both games with `build.py`. Please read [LEGAL.md](LEGAL.md).

## What you get

- **Both complete games** on one 32 MiB cartridge, 100 % of their original content, unchanged.
- **A new start screen:** Golden Sun's original intro with its music, then a slow panorama from the Golden Sun intro
  scene over to The Lost Age's valley with the Jupiter Lighthouse, The Lost Age logo and a menu in the games' own
  style: *Continue*, *Chapter 1 · Golden Sun*, *Chapter 2 · The Lost Age*.
- **Separate saves** for both games on the same cartridge (128 KiB Flash, one half per game).
- **Seamless chapter change:** when Golden Sun's credits end, the game saves automatically, shows
  "Chapter 2 – The Lost Age" and starts The Lost Age with **your party imported automatically** — levels, stats,
  Djinn, items, equipment, coins, names and story choices, exactly like the original link-cable transfer, but
  without cables, passwords or questions.
- **Languages:** English (from the USA/Europe games) and German (from the German games). One cartridge per language.

## Quick start

1. Install [Python](https://www.python.org/downloads/) 3.10 or newer.
2. Download this project (green **Code** button → *Download ZIP*, or `git clone`) and unpack it.
3. In the project folder: `python -m pip install -r requirements.txt`
4. Build:

   ```
   python build.py --gs1 "Golden Sun (USA, Europe).gba" --tla "Golden Sun - The Lost Age (USA, Europe).gba"
   ```

   (`.zip` files work too.) The result is `golden_sun_collection_en.gba` (or `_de` for German), built in seconds.
5. Play it in an emulator such as [mGBA](https://mgba.io/) or on a flash cart (see below).

Step-by-step instructions for Windows, macOS and Linux, and troubleshooting: **[BUILDING.md](BUILDING.md)**.

## Which ROMs

You need both games **in the same language**, dumped from your own cartridges. The builder checks them against the
verified No-Intro dumps:

| Game | File (No-Intro name) | SHA-1 |
|---|---|---|
| Golden Sun | Golden Sun (USA, Europe).gba | `5c4695205413df7db52b9a184815a07783999971` |
| Golden Sun: The Lost Age | Golden Sun - The Lost Age (USA, Europe).gba | `b500663220cb9bf56b9f8e8c0c544f1d6fa3a824` |
| Golden Sun (German) | Golden Sun (Germany).gba | `c23ab91a39434623cf1a999f387d743ade1a22a6` |
| Golden Sun: Die vergessene Epoche | Golden Sun - Die Vergessene Epoche (Germany).gba | `7820b4c7ba9002b0e9be23a6f45a9ab204986438` |

The finished cartridge always has the same checksum, so you can tell your build is correct:
English `3fde5ab3ae785e78d4e5125a87e041955cdf1595`, German `9d87b87fa2437e19a6be82ff50fced38bbdc7321`
(`build.py` compares this for you).

## Playing

- **Emulators:** tested in mGBA. The cartridge declares 128 KiB Flash saving, which mGBA detects automatically. In
  other emulators set the save type to *Flash 128K* (1 Mbit) if it is not detected.
- **Flash carts / real hardware:** not tested yet. The cart must support 128 KiB Flash saves (FLASH1M).
- **Saves:** the cartridge's save file holds both games. Save files from the separate original games cannot be used
  directly.
- **Start menu:** *Continue* opens The Lost Age if it has a save, otherwise Golden Sun; *Chapter 1/2* open Golden Sun or
  The Lost Age
  (each with its own title screen, so you can still load any of its save slots or start a new game).

## Known limitations

- Real hardware and flash carts are untested.
- Only the four verified dumps listed above are supported. Other revisions or languages (French, Italian, Spanish)
  are not supported yet.
- The ending of Golden Sun was tested in parts (final battle, ending scenes, credits and the chapter change); a full
  start-to-finish run on the merged cartridge has not been automated yet. Bug reports are welcome (see below).

## Reporting problems

Open an issue and describe where it happened (game, place, what you did). **Never attach ROMs or ROM files** — a
screenshot and your save file (`.sav`) are enough.

## How it works (short)

The Lost Age stays unchanged at the start of the cartridge. Golden Sun is moved into the upper 16 MiB, and every
address in it is adjusted. A small program of our own runs at power-on (start screen, menu, chapter change, party
transfer). Everything original — both games, the logo, the intro and title pictures, the music — is read from your
ROMs while building. Details for developers: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and
[docs/TECHNICAL.md](docs/TECHNICAL.md).

## Credits and licence

- Code of this project: MIT licence, see [LICENSE](LICENSE). It does not cover Golden Sun itself.
- Third-party code and models: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (including Karanum's
  *gs2-randomiser2*, whose Golden Sun decompression this project ports).
- The middle part of the start-screen panorama was generated locally with the Z-Image Turbo image model
  (Tongyi-MAI, Apache 2.0) through ComfyUI.
- This project was built with the help of an AI coding assistant (Claude, by Anthropic).
- *Golden Sun* is a trademark of Nintendo. This is an unofficial fan project, not affiliated with or endorsed by
  Nintendo or Camelot Software Planning.
