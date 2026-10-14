# Golden Sun Collection

Play **Golden Sun** and **Golden Sun: The Lost Age** as one game: both on a single Game Boy Advance cartridge,
with your party carried over automatically from the first game to the second.

This is a free fan project. **It contains no game files** — you create the cartridge yourself from your own
copies of the two games (see [LEGAL.md](LEGAL.md)).

> ⚠️ **Early release — please keep backups of your save file.**
> All of Golden Sun's maps and battles, saving, the start menu and the switch from the first to the second game
> have been tested (The Lost Age itself runs unchanged), but **nobody has played the whole story from start to
> finish on this cartridge yet**. Small glitches are possible, mostly in Golden Sun. If you run into anything odd,
> please [report it](#something-went-wrong).

## Features

- 🎮 **Two games, one cartridge** — no switching between ROMs.
- 📖 **One continuous story** — when Golden Sun's credits end, The Lost Age starts right away as *Chapter 2*.
- 🧙 **Your party carries over** — Isaac's team joins Felix with their levels, Djinn, items, equipment, coins and
  names, just like the original transfer between the two games.
- 🔌 **No link cable, no second Game Boy, no password** — the transfer happens on its own.
- 💾 **Separate saves** — each game keeps its own save files on the same cartridge.
- ↩️ **Play either game any time** — a start menu with *Continue*, *Chapter 1 · Golden Sun* and
  *Chapter 2 · The Lost Age*.
- 🌄 **New start screen** — Golden Sun's original intro and music, flowing into a view from Mt. Aleph to the
  Jupiter Lighthouse.
- ✅ **Nothing cut** — both games are complete and unchanged.
- 🌍 **English, German, French, Italian or Spanish**.

## What you need

1. **Your own copies of both games as ROM files** (`.gba`, or `.zip` files containing them), in the **same
   language**:
   - **English:** *Golden Sun* (USA/Europe) **and** *Golden Sun: The Lost Age* (USA/Europe)
   - **German:** *Golden Sun* (German) **and** *Golden Sun: Die vergessene Epoche* (German)
   - **French:** *Golden Sun* (French) **and** *Golden Sun: L'Âge Perdu* (French)
   - **Italian:** *Golden Sun* (Italian) **and** *Golden Sun: L'Era Perduta* (Italian)
   - **Spanish:** *Golden Sun* (Spanish) **and** *Golden Sun: La Edad Perdida* (Spanish)

   A ROM file is a copy of a game cartridge. You make it from your own cartridge with a cartridge reader (for
   example GBxCart RW or GB Operator). This project does not provide ROMs.
2. **A computer** with Windows, macOS or Linux.
3. **An emulator** to play, for example [mGBA](https://mgba.io/) (free), or a flash cart.

## How to install and play

**1. Install Python** (free, needed once): download it from [python.org/downloads](https://www.python.org/downloads/)
and install it. On Windows, tick **"Add python.exe to PATH"** at the bottom of the first installer screen.

**2. Download this project:** click the green **Code** button at the top of this page → **Download ZIP**, then
unpack the ZIP file (for example onto your Desktop).

**3. Copy your two ROM files into the `roms` folder** inside the unpacked folder. `.gba` or `.zip` files are both
fine, and the file names do not matter.

**4. Double-click the build file for your computer:**

| Windows | macOS | Linux |
|---|---|---|
| `Build (Windows).bat` | `Build (macOS).command` | `build-linux.sh` |

The first start takes about a minute to set itself up. A window then shows which games were found and builds your
cartridge in a few seconds. If your computer asks whether to run the file: on Windows choose **More info → Run
anyway**; on a Mac **right-click the file → Open → Open**; on Linux choose **Run** (or start it in a terminal with
`./build-linux.sh`).

**5. Play:** open the new file `golden_sun_collection_en.gba` (German `_de`, French `_fr`, Italian `_it`, Spanish
`_es`) in an emulator
such as [mGBA](https://mgba.io/) — *File → Load ROM*. Keep the `.sav` file that appears next to it: it holds the
saves of **both** games.

Something not working? The build window tells you what is wrong (for example a missing or damaged ROM file).
More help, and the manual way with typed commands: [BUILDING.md](BUILDING.md).

## Playing

### The start menu

The start menu only chooses **which game** starts; you then pick your save file in that game's own title screen,
as usual.

| Menu entry | What it does |
|---|---|
| *Continue* (appears once you have saved) | Starts The Lost Age if it has a save, otherwise Golden Sun |
| *Chapter 1 · Golden Sun* | Starts Golden Sun — load any Golden Sun save or start again |
| *Chapter 2 · The Lost Age* | Starts The Lost Age — load any Lost Age save or start a new game |

So once you are playing The Lost Age, *Continue* takes you there, and your Golden Sun saves are always reachable
through *Chapter 1*.

### From Golden Sun to The Lost Age

When Golden Sun's credits end, the game saves your finished game automatically (your normal Golden Sun saves are
not touched), shows **"Chapter 2"** and starts **a new game of The Lost Age**. You name Felix, and Isaac's party
joins your story later with everything they had at the end of Golden Sun.

> **Important: finish Golden Sun first, then play The Lost Age.**
> Your Golden Sun party is copied into The Lost Age **only when a new Lost Age game starts** — just like in the
> original games. A Lost Age game you started *before* finishing Golden Sun keeps the standard Isaac and his team,
> even if you finish Golden Sun later. To play with your own party, start a new Lost Age game after finishing
> Golden Sun (the switch to Chapter 2 does this for you). When you save that new game, be careful not to overwrite
> an older Lost Age save you want to keep.

Good to know:

- Switched the game off right after "Chapter 2", before saving? Nothing is lost: choose *Chapter 2* → New Game and
  your party is brought over again.
- Once you have finished Golden Sun on this cartridge, every new Lost Age game brings your party over
  automatically. Before that, The Lost Age asks about a transfer as in the original (so a password still works).
- Finishing Golden Sun again replaces the stored party with your latest run.
- Save files from the separate original games cannot be used with this cartridge.

### Emulators and flash carts

- **mGBA:** works out of the box (tested).
- **Other emulators:** if saving does not work, set the save type to **Flash 128K** (also called 1 Mbit).
- **Flash carts / a real Game Boy Advance:** not tested yet. The flash cart must support 128 KB Flash saves.

### Cheat codes

- Codes that change items, coins, stats and the like (RAM codes) work in both games.
- Codes that change the game program (ROM codes, many GameShark/Action Replay "master codes") work in The Lost Age
  but **not in Golden Sun**.
- **Only switch on cheats for the game you are playing**, and switch them off before changing games — both games
  use the same memory for different things, so a cheat for one can break the other.
- The games' own secret button codes are unchanged and should work as usual (not all were tested).

## Status and known limitations

- **Not yet played from start to finish.** Tested so far: all 201 Golden Sun maps, all 255 Golden Sun enemy
  groups, saving and loading in both games, the start menu, and the end of Golden Sun (final battle, ending,
  credits, switch to Chapter 2 with the party transfer). The Lost Age runs unchanged and was tested at its start
  and with saving. A complete playthrough of both games is still missing.
- **Small glitches are possible, mostly in Golden Sun** (for example a garbled sprite), because Golden Sun had to
  be moved inside the cartridge. The Lost Age is unchanged. Please [report](#something-went-wrong) where you saw
  one.
- Flash carts and real hardware are untested.
- Supported: the English (USA/Europe), German, French, Italian and Spanish versions. The Japanese versions are not.

## Something went wrong?

- **The builder shows an error:** see the table in [BUILDING.md](BUILDING.md#troubleshooting) — it covers wrong
  or damaged ROM files, mixed languages and missing packages.
- **Something looks or behaves wrong in the game:** please open an
  [issue](../../issues) and describe where it happened (which game, which place, what you did just before).
  A screenshot and your `.sav` file help. **Never attach or link ROM files.**

---

## For the curious

<details>
<summary>How the builder knows your ROM is correct</summary>

Every correct copy of the same cartridge is byte-for-byte identical, no matter who made it. The builder compares a
"fingerprint" (SHA-1 checksum) of your file with the fingerprint of the correct copy, as listed by the
preservation project No-Intro. Damaged copies or already patched ROMs are rejected; files that a reader padded with
empty space or cut short at the end are adjusted automatically.

| ROM | SHA-1 |
|---|---|
| Golden Sun (USA, Europe) | `5c4695205413df7db52b9a184815a07783999971` |
| Golden Sun - The Lost Age (USA, Europe) | `b500663220cb9bf56b9f8e8c0c544f1d6fa3a824` |
| Golden Sun (Germany) | `c23ab91a39434623cf1a999f387d743ade1a22a6` |
| Golden Sun - Die Vergessene Epoche (Germany) | `7820b4c7ba9002b0e9be23a6f45a9ab204986438` |
| Golden Sun (France) | `42f3b262c16cfc5bde1fa2b25016fb74046de1b3` |
| Golden Sun - L'Age Perdu (France) | `f14855c0f8c87a95cc52189e8e3b2bd9df186322` |
| Golden Sun (Italy) | `ca45e04b26b2f040ac63e679a459d21869f5f28d` |
| Golden Sun - L'Era Perduta (Italy) | `57f1d005666b81645e55412658427e27099c5907` |
| Golden Sun (Spain) | `de0bdc889594b012cad213ca83707feb81ada28b` |
| Golden Sun - La Edad Perdida (Spain) | `a2e3e80036195343c2713410ac14f4e329e3f40d` |

Finished cartridge: English `5a8c4f2a5542a9fb745f21b8b4e804d4158043d1`,
German `9d87b87fa2437e19a6be82ff50fced38bbdc7321`, French `2de01797b30807c289f79e7cd7c4afa7026c7cb3`,
Italian `569f1cbbfc5f27cd53572bf8c5658af1a02470ae`, Spanish `d64dedca0a0c245f0315452eb4da8656df4b4c26`.

</details>

<details>
<summary>How it works</summary>

The Lost Age stays unchanged at the start of the cartridge. Golden Sun is moved into the upper half, and every
address inside it is adjusted. A small program of our own runs when you switch the game on (start screen, menu,
switch to Chapter 2, party transfer). Everything original — both games, the logo, the intro and title pictures, the
music — is taken from your ROM files while building. For developers: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
and [docs/TECHNICAL.md](docs/TECHNICAL.md).

</details>

## Credits and licence

- Code of this project: MIT licence, see [LICENSE](LICENSE). It does not cover Golden Sun itself.
- Third-party code and models: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (including Karanum's
  *gs2-randomiser2*, whose Golden Sun decompression this project ports).
- The middle part of the start-screen panorama was generated locally with the Z-Image Turbo image model
  (Tongyi-MAI, Apache 2.0) through ComfyUI (see AI disclosure).
- *Golden Sun* is a trademark of Nintendo. This is an unofficial fan project, not affiliated with or endorsed by
  Nintendo or Camelot Software Planning. Please do not share built cartridges or ROMs ([LEGAL.md](LEGAL.md)).

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
