# Golden Sun Collection 1.2.2

**The "Chapter 2" card is visible again, and Golden Sun has been played through on the cartridge.**

- Fixed: after the Golden Sun credits the screen stayed black for about 4 seconds instead of showing the
  "Chapter 2" card before The Lost Age started. Golden Sun's title screen leaves the screen scaled and faded out;
  the card now resets both before it is shown. All five languages.
- New test: a complete playthrough of Golden Sun (English: all chapters, side quests, final battle, credits) is
  replayed on the cartridge and compared with the original game after every game step. It matches from power-on to
  the end of the credits; the only problem it found was the card above. Developers can run it themselves with
  `tools/playthrough/playthrough.py` (see docs/TESTING.md).

Everything else was tested again in all five languages (all maps, all enemy groups, saving, the start menu and the
switch to Chapter 2). Your save files keep working.

**This release contains no game files.** Download the source code below, copy your two ROM files (same language)
into the `roms` folder and double-click `Build (Windows).bat`, `Build (macOS).command` or `build-linux.sh`.
Details: README.md and BUILDING.md.

Reference checksums of the finished cartridge (SHA-1), checked by the builder: English
`b35d82311df18723797b35f9e9ec572a4abffe97`, German `2563db4c1456c296407ee900994527065985b517`, French
`bcad2189bc5734710e97ca40d993d6ba51c4250d`, Italian `528c785bee43df2439ae0a07badebe66cbca8cfa`, Spanish
`20c853dd089a4e5cf1b8365f82dce7ed2a5d554f`.

Made with AI assistance (Claude Code with Claude Opus 5.5); see the AI disclosure in README.md. Unofficial fan
project, not affiliated with Nintendo or Camelot. Please do not share built cartridges or ROMs.
