# Changelog

## 1.0.0 — first release

- Golden Sun and Golden Sun: The Lost Age on one 32 MiB cartridge (English from the USA/Europe games, German from
  the German games).
- Start screen: Golden Sun's original intro with its music, panning panorama from the Golden Sun intro scene to
  The Lost Age's valley, The Lost Age logo, game-style menu (Continue / Chapter 1 / Chapter 2).
- Separate saves for both games (128 KiB Flash, one half per game).
- Chapter change at the end of Golden Sun: automatic save, "Chapter 2" card, new game of The Lost Age with the
  Golden Sun party imported automatically (link-transfer quality, no passwords).
- Builder `build.py`: checks the ROMs against the verified dumps (padded or trimmed dumps are adjusted
  automatically), accepts .zip, detects the language, needs only
  Python with Pillow and capstone, and produces a byte-identical cartridge on every system.
- Verified with automated tests: all 201 Golden Sun maps and all 255 enemy groups (no wrong ROM accesses, no
  crashes), saves, start menu, chapter change, final battle, ending and credits.
- Fixed: a garbled sprite above Isaac in the Vale prologue (bedroom scene) and about 115 other data values that the
  relocation took for pointers.
