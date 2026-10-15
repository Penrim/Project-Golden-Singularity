# Golden Sun Collection 1.2.1

**About 50 more fixes per language inside the moved Golden Sun.**

To fit both games on one cartridge, Golden Sun is moved and every internal address in it is adjusted. Version 1.2.0
proved about 96 % of the ~32 000 candidate values from the game's own code and file formats; this version takes that
to about 99 %. On the way it found about 50 more values per language that are not addresses but were adjusted as if
they were. Fixed in English, German, French, Italian and Spanish:

- Letters of the menu font and of the staff roll (single wrong pixels).
- The bobbing of the menu cursor.
- Frames of several monster and effect sprites and some packed images (wrong pixels).
- Three bytes in songs, one value in the item table and small number tables of two battle effects.
- German: one colour of a menu palette. Spanish: positions in a mini-game table.

Everything was tested again in all five languages (all maps, all enemy groups, saving, the start menu and the switch
to Chapter 2). Your save files keep working. Please keep reporting anything odd.

**This release contains no game files.** Download the source code below, copy your two ROM files (same language)
into the `roms` folder and double-click `Build (Windows).bat`, `Build (macOS).command` or `build-linux.sh`.
Details: README.md and BUILDING.md.

Reference checksums of the finished cartridge (SHA-1), checked by the builder: English
`e110dbeae2e42336dd83f6b8d2cf7813ae95ec81`, German `3b3c8ea4830f045bf9eece1cb159c5a8de0834cf`, French
`ccd5c61c7a26e4f8f9bd7a6f1336c2b5407e61a0`, Italian `2573e44805e054d60385057a2f0db6ab72c8b7c4`, Spanish
`4afaadffc4c41d48eff554c5fd4523c1bb49103c`.

Made with AI assistance (Claude Code with Claude Opus 5.5); see the AI disclosure in README.md. Unofficial fan
project, not affiliated with Nintendo or Camelot. Please do not share built cartridges or ROMs.
