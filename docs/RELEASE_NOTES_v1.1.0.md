# Golden Sun Collection 1.1.0

Play **Golden Sun** and **Golden Sun: The Lost Age** as one game, both on a single Game Boy Advance cartridge,
with your party carried over automatically. Built from **your own** copies of the two games.

**New: French, Italian and Spanish.** The collection now works in five languages: English, German, French,
Italian and Spanish (one cartridge per language, built from both games in that language).

> ⚠️ **Early release.** Golden Sun's maps and battles, saving, the start menu and the switch to Chapter 2 are
> tested in all five languages, but nobody has played the whole story from start to finish on this cartridge yet.
> Small glitches are possible, mostly in Golden Sun. Please keep backups of your save file and report anything odd.

**This release contains no game files.** Download the source code below and build the cartridge yourself.

## What's new
- French, Italian and Spanish versions, with translated start menu and "Chapter 2" screen.
- The builder recognises the new ROMs automatically (also as .zip) and builds every language for which both
  games are present.
- Start screen: the Lost Age logo is now cut out cleanly in every language. In English, a small piece of the
  logo's ornament that was missing before is back.

## How to build
1. Install [Python](https://www.python.org/downloads/) (Windows: tick "Add python.exe to PATH").
2. Download **Source code (zip)** below and unpack it.
3. Copy your two ROM files (same language) into the `roms` folder.
4. Double-click `Build (Windows).bat`, `Build (macOS).command` or `build-linux.sh`.
5. Open `golden_sun_collection_<language>.gba` (`en`, `de`, `fr`, `it` or `es`) in an emulator such as mGBA.

Already on 1.0.0? Your save file keeps working: just build again and use the new `.gba` with your old `.sav`.

Reference checksums of the finished cartridge (SHA-1), checked by the builder:

| Language | SHA-1 |
|---|---|
| English | `5a8c4f2a5542a9fb745f21b8b4e804d4158043d1` |
| German | `9d87b87fa2437e19a6be82ff50fced38bbdc7321` |
| French | `2de01797b30807c289f79e7cd7c4afa7026c7cb3` |
| Italian | `569f1cbbfc5f27cd53572bf8c5658af1a02470ae` |
| Spanish | `d64dedca0a0c245f0315452eb4da8656df4b4c26` |

Details and help: README.md and BUILDING.md.

Made with AI assistance (Claude Code with Claude Opus 5.5; one part of the start screen generated with Z-Image
Turbo); see the AI disclosure in README.md. Unofficial fan project, not affiliated with Nintendo or Camelot.
Please do not share built cartridges or ROMs.
