# Building the Golden Sun Collection

You need your own dumps of **Golden Sun** and **Golden Sun: The Lost Age** in the same language (see the table in
[README.md](README.md#which-roms)) and Python. Nothing else: no compiler, no other tools.

## 1. Get your ROMs

Dump both cartridges you own with a cartridge dumper (for example GBxCart RW, GB Operator or a similar device) and
keep the `.gba` files (or `.zip` files containing them). Downloading ROMs of games you do not own is not legal in
most countries; this project does not provide or link to ROMs.

## 2. Install Python

- **Windows:** install Python 3.10 or newer from [python.org](https://www.python.org/downloads/) and tick
  *Add python.exe to PATH* in the installer. Open *Command Prompt* or *PowerShell*.
- **macOS:** install Python from [python.org](https://www.python.org/downloads/) (or `brew install python`).
  Use `python3` instead of `python` below.
- **Linux:** Python 3.10+ is usually installed; otherwise install it with your package manager (e.g.
  `sudo apt install python3 python3-venv`). Use `python3` instead of `python` below.

## 3. Get the project

Download it from GitHub (green **Code** button → *Download ZIP*) and unpack it, or:

```
git clone <repository URL>
cd <repository folder>
```

## 4. Install the two Python packages

Optional but recommended: a virtual environment, so nothing is installed system-wide.

```
python -m venv .venv
.venv\Scripts\activate          (Windows)
source .venv/bin/activate        (macOS / Linux)
```

Then:

```
python -m pip install -r requirements.txt
```

This installs Pillow (images) and capstone (reads the game code) in the exact versions the reference build uses.

## 5. Build

```
python build.py --gs1 "path/to/Golden Sun (USA, Europe).gba" --tla "path/to/Golden Sun - The Lost Age (USA, Europe).gba"
```

German:

```
python build.py --gs1 "path/to/Golden Sun (Germany).gba" --tla "path/to/Golden Sun - Die Vergessene Epoche (Germany).gba"
```

- `.zip` files work as well.
- The language is detected from the ROMs.
- The cartridge is written to `golden_sun_collection_en.gba` / `golden_sun_collection_de.gba` in the project
  folder (choose another place with `--out file.gba`).
- At the end the builder prints the SHA-1 checksum and tells you whether it matches the reference build.

## 6. Play

Open the `.gba` file in [mGBA](https://mgba.io/) (recommended) or another emulator. The save type is
*Flash 128K*; mGBA detects it automatically. Keep the cartridge's `.sav` file: it holds the saves of both games.

## Troubleshooting

| Message | What to do |
|---|---|
| `missing Python packages` | Run `python -m pip install -r requirements.txt` (in the activated virtual environment). |
| `this is not Golden Sun` / `not ... The Lost Age` | `--gs1` and `--tla` are swapped, or the file is another game. |
| `SHA-1 ... does not match the correct copy` | Your file's game data differs from the original: a damaged dump (dump again, clean the contacts), a patched/translated ROM, or another game version. Padded or trimmed files are fine, the builder adjusts their size itself. `--force` tries anyway (untested, may not work). |
| `the two ROMs are different languages` | Use both USA/Europe games or both German games. |
| checksum differs from the reference build | Usually other package versions: install exactly `requirements.txt`. The game may still work. |
| the emulator says it cannot save / shows a save error | Set the save type to *Flash 128K* (1 Mbit) and restart. |

## Developers

To change the cartridge code or the hooks, you need more tools (Windows instructions; see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for everything):

- `python -m pip install -r requirements-dev.txt` (adds keystone-engine, the assembler for the hooks; new snippets
  are cached in `data/asm_cache.json`).
- The Arm GNU Toolchain 14.2 in `tools/armgcc/` or on `PATH` (`arm-none-eabi-gcc`): with it, the build recompiles
  `cart/runtime.c` and refreshes `cart/prebuilt/`.
- Changed menu texts: `python tools/bootmenu.py ui` (needs the Windows fonts Georgia and Verdana).
- Tests need the mGBA development build (see docs/TESTING.md).

After a change, update `EXPECTED_OUTPUT` in `build.py` and the checksums in README.md.
