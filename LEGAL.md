# Legal notes

This is an unofficial, non-commercial fan project. *Golden Sun* and *Golden Sun: The Lost Age* are © Nintendo /
Camelot Software Planning. *Golden Sun* is a trademark of Nintendo. This project is not affiliated with or endorsed
by Nintendo or Camelot.

## What this repository contains

Only material created for this project:

- source code (Python build tools, the C/assembly code that runs on the cartridge) and its compiled form;
- documentation;
- **references and numbers, not game data:** addresses, offsets and lists of where things are inside the original
  games (for example `art/gs1_intro_recipe.json`, `art/gs1_intro_timeline.json`, `data/*.txt`). They describe how
  to rebuild a picture or a scene from *your* ROM; they contain no graphics, music, text or code of the games;
- original artwork: the generated middle part of the start-screen panorama (`art/panorama_patch.png`, only the
  newly generated pixels), the generated background of the "Chapter 2" card (`art/card_bg.png`) and the rendered
  menu texts (`art/ui/`).

It does **not** contain any ROM, any part of a ROM, or any graphics, music, text or code taken from the games. The
logos, the intro, the title pictures and the music used by the cartridge are read from the ROMs you supply, at the
moment you build it on your own computer.

## What you may and may not do

- Build the cartridge only from dumps of cartridges **you own**.
- **Do not share the built `.gba` file**, ROMs, or patched ROMs, and do not ask for them in issues or discussions.
  Issues containing ROMs or links to ROMs will be removed.
- Do not sell the built cartridge or use this project commercially.

A classic patch file (IPS/BPS) is deliberately not offered: because the cartridge combines two games, any patch
against one of them would have to contain parts of the other game. The builder avoids that by working only with
files you already have.

## Licences

- This project's own code and documentation: MIT licence ([LICENSE](LICENSE)). The licence covers only this
  project's own work, not Golden Sun.
- Third-party code, libraries and models: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
