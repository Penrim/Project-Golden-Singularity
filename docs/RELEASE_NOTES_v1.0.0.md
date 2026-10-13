# Golden Sun Collection 1.0.0

Play **Golden Sun** and **Golden Sun: The Lost Age** as one game — both on a single Game Boy Advance cartridge,
with your party carried over automatically. Built from **your own** copies of the two games.

> ⚠️ **Early release.** Golden Sun's maps and battles, saving, the start menu and the switch to Chapter 2 are
> tested, but nobody has played the whole story from start to finish on this cartridge yet. Please keep backups of
> your save file and report anything odd.

**This release contains no game files.** Download the source code below and build the cartridge yourself.

## Highlights
- Both complete games, unchanged, on one cartridge — English or German.
- One continuous story: when Golden Sun's credits end, The Lost Age starts with your party imported automatically
  (no link cable, no password).
- Separate saves for both games, and a start menu to play either chapter any time.
- New start screen with Golden Sun's original intro and music.

## How to build
1. Install [Python](https://www.python.org/downloads/) (Windows: tick "Add python.exe to PATH").
2. Download **Source code (zip)** below and unpack it.
3. Copy your two ROM files into the `roms` folder.
4. Double-click `Build (Windows).bat`, `Build (macOS).command` or `build-linux.sh`.
5. Open `golden_sun_collection_en.gba` (or `_de` for German) in an emulator such as mGBA.

Details and help: README.md and BUILDING.md. Reference checksums of the finished cartridge (SHA-1): English
`3fde5ab3ae785e78d4e5125a87e041955cdf1595`, German `9d87b87fa2437e19a6be82ff50fced38bbdc7321` — the builder
checks this for you.

Made with AI assistance (Claude Code with Claude Opus 5.5; one part of the start screen generated with Z-Image
Turbo) — see the AI disclosure in README.md. Unofficial fan project, not affiliated with Nintendo or Camelot.
Please do not share built cartridges or ROMs.
