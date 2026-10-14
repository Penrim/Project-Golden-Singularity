# Golden Sun Collection 1.2.0

**About 300 fixes per language inside the moved Golden Sun.**

To fit both games on one cartridge, Golden Sun is moved and every internal address in it is adjusted. Until now the
builder partly had to guess which values are addresses. For this version every one of the ~32 000 candidate values
was checked against how the game really uses it: by analysing the game's code and file formats and by recording the
game while it runs. About 96 % of them are now proven; the rest
(mostly tables only used in menus, Psynergy, summons and story scenes) is decided as before and is the next step.
That turned up values the builder changed although they are not addresses (and one address it
missed). Fixed in English, German, French, Italian and Spanish:

- Animation scripts of characters and monsters (frames shown one tick too long) and sprite frames (wrong pixels).
- Sprite position offsets (1 pixel off).
- Seven places in the program code where a value was divided by 32 instead of halved.
- Instrument samples and three note velocities in the music.
- Three coordinates in a map script, the fill pattern of a battle effect and several small number tables.
- One sprite frame that pointed into The Lost Age's half of the cartridge.

Everything was tested again in all five languages (all maps, all enemy groups, saving, the start menu and the switch
to Chapter 2). Your save files keep working. Small glitches are still possible, mostly in Golden Sun, so please keep
reporting anything odd.

**This release contains no game files.** Download the source code below, copy your two ROM files (same language)
into the `roms` folder and double-click `Build (Windows).bat`, `Build (macOS).command` or `build-linux.sh`.
Details: README.md and BUILDING.md.

Reference checksums of the finished cartridge (SHA-1), checked by the builder: English
`a83b1f8d8341d61ec2c3d876f147c08ad00c167e`, German `16ed34817a4979e287542fb1cf09880ac78b12a0`, French
`a89efc230b36cb59e14b16fb53d4698f4da5c511`, Italian `9b1cd79036b7e1c9e18ebc13109dcd1b45e37610`, Spanish
`5ca0e8cd944094808b4a2774ee4fb4a985e1c581`.

Made with AI assistance (Claude Code with Claude Opus 5.5); see the AI disclosure in README.md. Unofficial fan
project, not affiliated with Nintendo or Camelot. Please do not share built cartridges or ROMs.
