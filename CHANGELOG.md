# Changelog

## 1.2.2 — the "Chapter 2" card is visible again; Golden Sun played through on the cartridge

- Fixed: the "Chapter 2" card after the Golden Sun credits was invisible (about 4 seconds of black screen before
  The Lost Age started). Golden Sun's title screen leaves the screen scaled and faded out; the card now resets
  both before it is shown. All five languages.
- New test: a complete playthrough of Golden Sun (English) is replayed on the cartridge and compared with the
  original game step by step (`tools/playthrough/`, see docs/TESTING.md). It found the invisible card above.

## 1.2.1 — about 50 more fixes per language in the moved Golden Sun

The check of every value that the builder adjusts when it moves Golden Sun is now complete except for about 1 %
(was 4 %). That found about 50 more values per language that are not addresses but were changed as if they were.
Fixed in all five languages:

- Letters of the menu font and of the staff roll (single wrong pixels).
- The bobbing of the menu cursor.
- Frames of several monster and effect sprites (wrong pixels) and packed images.
- Three bytes in songs, one value in the item table, small number tables of two battle effects.
- German: one colour of a palette in the menus. Spanish: positions in a mini-game table.

All maps, all enemy groups, saving, the start menu and the switch to Chapter 2 were tested again in all five
languages. Save files keep working.

## 1.2.0 — about 300 fixes per language in the moved Golden Sun

Golden Sun has to be moved inside the cartridge, and every internal address in it is adjusted. Until now that
decision ("address or just a number?") was partly guessed. For this version every one of the ~32 000 candidate
values was checked against how the game actually uses it (code analysis, file formats, recordings of the game
running); about 96 % are proven now, the rest is decided as before. That found values the builder had changed although they are not addresses, and one address it missed.
Fixed in all five languages (about 300 values per language):

- Animation scripts of characters and monsters (frame durations off by one tick) and sprite frames (wrong pixels,
  the same kind as the garbled sprite above Isaac fixed in 1.0.0); sprite position offsets (1 pixel).
- Seven program instructions where a value was divided by 32 instead of halved.
- Sound: about 170 bytes of instrument samples and three note velocities in songs.
- Three coordinates in a map script, the fill pattern of a battle effect, and several small number tables.
- A sprite frame (sprite 204) that pointed into The Lost Age's half of the cartridge.

All maps, all enemy groups, saving, the start menu and the switch to Chapter 2 were tested again in all five
languages. Save files keep working.

## 1.1.1 — fix: building works again

- Fixed: building stopped with "cart/prebuilt/... does not match cart/runtime.c" for everyone who downloaded the
  project (GitHub ZIP or git clone) and has no ARM compiler installed, which is every player. Versions 1.0.0 and
  1.1.0 were affected. The finished cartridges are unchanged (same checksums as 1.1.0).

## 1.1.0 — French, Italian and Spanish

- New languages: French, Italian and Spanish (built from the French/Italian/Spanish games, as with English and
  German). The builder recognises the new ROMs automatically.
- Start screen: The Lost Age's subtitle is now removed reliably from the logo in every language; in English a
  small piece of the logo's ornament that was cut off before is back (the English cartridge checksum changes).

## 1.0.0 — first release

- Golden Sun and Golden Sun: The Lost Age on one 32 MiB cartridge (English from the USA/Europe games, German from
  the German games).
- Start screen: Golden Sun's original intro with its music, panning panorama from the Golden Sun intro scene to
  The Lost Age's valley, The Lost Age logo, game-style menu (Continue / Chapter 1 / Chapter 2).
- Separate saves for both games (128 KiB Flash, one half per game).
- Chapter change at the end of Golden Sun: automatic save, "Chapter 2" card, new game of The Lost Age with the
  Golden Sun party imported automatically (link-transfer quality, no passwords).
- Easy build: copy the ROMs into `roms/` and double-click `Build (Windows).bat`, `Build (macOS).command` or
  `build-linux.sh` (sets up its own Python environment on first start, finds and checks the ROMs itself, builds
  every language that is complete).
- Builder `build.py`: checks the ROMs against the verified dumps (padded or trimmed dumps are adjusted
  automatically), accepts .zip, detects the language, needs only
  Python with Pillow and capstone, and produces a byte-identical cartridge on every system.
- Verified with automated tests: all 201 Golden Sun maps and all 255 enemy groups (no wrong ROM accesses, no
  crashes), saves, start menu, chapter change, final battle, ending and credits.
- Fixed: a garbled sprite above Isaac in the Vale prologue (bedroom scene) and about 115 other data values that the
  relocation took for pointers.
