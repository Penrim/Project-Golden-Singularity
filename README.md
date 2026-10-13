# Golden Sun Collection

**Golden Sun** and **Golden Sun: The Lost Age** on one Game Boy Advance cartridge, joined into one continuous
story. A fan-made ROM hack for your own legally dumped cartridges.

> **No game files are included or distributed here.** You build the cartridge yourself from your own dumps of
> both games with `build.py`. Please read [LEGAL.md](LEGAL.md).

## Features

- 🎮 **Two games, one cartridge** — play Golden Sun and The Lost Age without switching ROMs.
- 📖 **One continuous story** — when Golden Sun's credits end, The Lost Age starts right away as *Chapter 2*.
- 🧙 **Your party carries over** — Isaac's team joins Felix with their levels, stats, Djinn, items, equipment,
  coins and names, just like the original "Clear Data" transfer.
- 🔌 **No link cable, no second Game Boy, no password** — the transfer happens automatically, nothing to type in.
- 💾 **Separate saves for both games** — each game keeps its own save slots on the same cartridge.
- ↩️ **Jump in anywhere** — the start menu offers *Continue*, *Chapter 1 · Golden Sun* and
  *Chapter 2 · The Lost Age*, so you can replay Golden Sun or start The Lost Age fresh at any time.
- 🌄 **New start screen** — Golden Sun's original intro with its music, flowing into a panorama from Mt. Aleph to
  the Jupiter Lighthouse.
- ✅ **The original games, untouched** — 100 % of both games' content, music and translations.
- 🌍 **English and German** — built from the USA/Europe or the German games.

<details>
<summary>More details</summary>

- Saves: 128 KiB Flash, one half per game; the chapter change saves Golden Sun's clear data automatically.
- The transfer imports the same data as the original link-cable transfer between the two games.
- One cartridge per language: both ROMs must be the same language.

</details>

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

A **ROM** is a copy of a game cartridge as a file (`.gba`). You make it yourself from your own cartridge with a
cartridge reader ("dumper"); see [BUILDING.md](BUILDING.md#1-get-your-roms).

You need **two ROMs in the same language** — pick one of the two pairs:

| To build… | you need these two ROMs |
|---|---|
| the **English** cartridge | *Golden Sun* (USA/Europe) **and** *Golden Sun: The Lost Age* (USA/Europe) |
| the **German** cartridge | *Golden Sun* (German) **and** *Golden Sun: Die vergessene Epoche* (German) |

Mixing languages (e.g. English Golden Sun with German The Lost Age) does not work. Other languages (French,
Italian, Spanish) are not supported yet.

**You don't have to check anything yourself:** `build.py` checks automatically that each ROM is a correct,
unmodified copy of the original cartridge, and tells you if it is not (for example a damaged copy or an already
patched ROM). Every correct copy of the same cartridge is byte-for-byte identical, no matter who made it, so the
builder can recognise it. Files that a dumper padded with empty space or cut short at the end are adjusted
automatically. At the end it also confirms that your finished cartridge is identical to the reference build.

<details>
<summary>For the curious: the checksums the builder compares</summary>

A checksum (SHA-1) is a fingerprint of a file: if even one byte differs, the fingerprint changes. Because every
correct dump of the same cartridge contains exactly the same data, all of them have the same fingerprint. These are
the fingerprints of the correct ROMs (as listed by the preservation project No-Intro):

| ROM | SHA-1 |
|---|---|
| Golden Sun (USA, Europe) | `5c4695205413df7db52b9a184815a07783999971` |
| Golden Sun - The Lost Age (USA, Europe) | `b500663220cb9bf56b9f8e8c0c544f1d6fa3a824` |
| Golden Sun (Germany) | `c23ab91a39434623cf1a999f387d743ade1a22a6` |
| Golden Sun - Die Vergessene Epoche (Germany) | `7820b4c7ba9002b0e9be23a6f45a9ab204986438` |

Finished cartridge: English `3fde5ab3ae785e78d4e5125a87e041955cdf1595`,
German `9d87b87fa2437e19a6be82ff50fced38bbdc7321`.

</details>

## Playing

- **Emulators:** tested in mGBA. The cartridge declares 128 KiB Flash saving, which mGBA detects automatically. In
  other emulators set the save type to *Flash 128K* (1 Mbit) if it is not detected.
- **Flash carts / real hardware:** not tested yet. The cart must support 128 KiB Flash saves (FLASH1M).

## Saves and the start menu

The cartridge's save memory is split in two halves: one for Golden Sun, one for The Lost Age. Each game saves
exactly as in the original (its own three files, its own save menus) and never touches the other game's half.
Save files from the separate original games cannot be used directly.

**The start menu only chooses the game.** You pick your save file in that game's own title screen, as usual:

| Menu entry | Starts | Use it to… |
|---|---|---|
| *Continue* (shown once any save exists) | The Lost Age if it has a save, otherwise Golden Sun | jump straight into the furthest chapter |
| *Chapter 1 · Golden Sun* | Golden Sun's title screen | load any Golden Sun file, or start Golden Sun again |
| *Chapter 2 · The Lost Age* | The Lost Age's title screen | load any Lost Age file, or start a new Lost Age game |

So with saves in both games, *Continue* goes to The Lost Age; your Golden Sun files are always reachable through
*Chapter 1*.

**The chapter change:** when Golden Sun's credits end, the game saves its end-of-game data automatically (in a
reserved spot — your three normal Golden Sun files stay untouched), shows "Chapter 2" and starts a **new game** of
The Lost Age. You name Felix, and Isaac's party is imported automatically.

> **Important: finish Golden Sun first, then play The Lost Age.**
> Your Golden Sun party is copied into The Lost Age **only when a new Lost Age game starts** — just like the
> original cable/password transfer. A Lost Age game started *before* you finished Golden Sun keeps the default
> Isaac and his team, even if you finish Golden Sun later; loading that save will not update them. To play with
> your own Golden Sun party, start a new Lost Age game after finishing Golden Sun (the chapter change does this for
> you). When you save that new game, make sure you do not overwrite an older Lost Age file you want to keep.

Good to know:

- Turned the game off right after the chapter change, before saving in The Lost Age? Nothing is lost: choose
  *Chapter 2* → New Game and the party is imported again.
- Once Golden Sun has been finished on the cartridge, every new Lost Age game imports that party automatically (the
  original transfer question and password entry are skipped). Before that, The Lost Age asks about a transfer as
  in the original, so you can still enter a password.
- Finishing Golden Sun again replaces the end-of-game data with your latest run.

## Cheat codes

- **The games' own secrets** (button codes on the title screens etc.) should work as in the originals; they are
  not changed, but not all of them were tested.
- **Cheat devices / emulator cheats:** RAM codes (items, coins, stats, walking through walls, …) work in both games.
  Codes that patch the game program (ROM codes, many GameShark/Action Replay "master codes") work for The Lost Age
  but **not for Golden Sun**, because Golden Sun sits at a different place on this cartridge.
- Both games share the same memory addresses for different things: **enable cheats only for the game you are
  playing** and switch them off before changing games, or they can corrupt the other game.

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
  (Tongyi-MAI, Apache 2.0) through ComfyUI (details below).
- *Golden Sun* is a trademark of Nintendo. This is an unofficial fan project, not affiliated with or endorsed by
  Nintendo or Camelot Software Planning.

## AI disclosure

This project was made with AI assistance, directed and play-tested by its author:

- **Code, reverse engineering, tests and documentation** were written with **Claude Code** (Anthropic's agentic
  coding tool) using the **Claude Opus 5.5** model.
- **Start screen:** Claude Code also built the start screen — the code that takes the logo, the intro scenes and
  the music from your ROMs, the scripts and prompts for the image generation, and the choice of the generated
  variant. The only AI-generated image content is the **middle part of the panorama** (the transition between the
  Golden Sun and The Lost Age scenes), generated locally with **Z-Image Turbo** (Tongyi-MAI) in ComfyUI; the
  model, settings and prompt are documented in [art/README.md](art/README.md).
- Everything else you see and hear on the cartridge — both games, the logo, the intro, the title scenes, the
  music — comes unchanged from the original games, read from your ROMs.
