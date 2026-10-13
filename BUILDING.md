# Building the Golden Sun Collection

You need your own copies of **Golden Sun** and **Golden Sun: The Lost Age** in the same language (see
[README.md](README.md#what-you-need)) and Python. Nothing else: no compiler, no other tools.

## 1. Get your ROMs

Copy both cartridges you own with a cartridge reader (for example GBxCart RW, GB Operator or a similar device) and
keep the `.gba` files (or `.zip` files containing them). Downloading ROMs of games you do not own is not legal in
most countries; this project does not provide or link to ROMs.

## 2. Install Python

- **Windows:** install Python 3.10 or newer from [python.org](https://www.python.org/downloads/) and tick
  *Add python.exe to PATH* in the installer.
- **macOS:** install Python from [python.org](https://www.python.org/downloads/). (The Python that comes with macOS
  is too old.)
- **Linux:** Python 3.10+ is usually installed. On Debian/Ubuntu also install the venv module:
  `sudo apt install python3-venv`.

## 3. Get the project

Download it from GitHub (green **Code** button → *Download ZIP*) and unpack it, or `git clone` it.

## 4. Build — the easy way

1. Copy your two ROM files into the **`roms`** folder (names do not matter; `.gba` or `.zip`).
2. Double-click the build file for your system:
   - **Windows:** `Build (Windows).bat` — if Windows shows "Windows protected your PC", click **More info → Run
     anyway**.
   - **macOS:** `Build (macOS).command` — the first time, **right-click it → Open → Open** (macOS asks because the
     file was downloaded from the internet).
   - **Linux:** `build-linux.sh` — choose **Run** if your file manager asks, or run `./build-linux.sh` in a
     terminal.
3. The first start sets up a private Python environment in the folder `.venv` (about a minute, needs internet
   once). Then the window lists the ROM files it recognised and builds every language for which both games are
   present: `golden_sun_collection_en.gba` and/or `golden_sun_collection_de.gba` in the project folder.

## 5. Build — the manual way (typed commands)

Open a terminal in the project folder (Windows: click the folder's address bar, type `cmd`, Enter; macOS:
right-click the folder → *New Terminal at Folder*). Use `python3` instead of `python` on macOS/Linux.

```
python -m venv .venv
.venv\Scripts\activate          (Windows)
source .venv/bin/activate        (macOS / Linux)
python -m pip install -r requirements.txt
python build.py
```

`python build.py` searches the `roms` folder like the launchers do. To name the files yourself:

```
python build.py --gs1 "path/to/Golden Sun (USA, Europe).gba" --tla "path/to/Golden Sun - The Lost Age (USA, Europe).gba"
```

Options: `--out file.gba` (other output name), `--force` (accept ROMs that are not the verified copies; untested),
`--verbose` (show the builder's technical output).

## 6. Play

Open the `.gba` file in [mGBA](https://mgba.io/) (recommended) or another emulator. The save type is
*Flash 128K*; mGBA detects it automatically. Keep the cartridge's `.sav` file: it holds the saves of both games.

## Troubleshooting

| Message | What to do |
|---|---|
| `Python 3.10 or newer was not found` | Install Python (step 2). On Windows, re-run the installer and tick *Add python.exe to PATH*. Then start the build file again. |
| `Could not create the setup folder` (Linux) | `sudo apt install python3-venv`, then start again. |
| `The setup did not work` | The first start needs internet to download two small Python packages. Check the connection and start again. If it still fails, delete the `.venv` folder and retry. |
| `No cartridge built: both games of the same language are needed` | The list above it shows which file is missing (e.g. *add: The Lost Age (USA/Europe)*). Copy it into `roms`. |
| a file is listed as `not one of the supported Golden Sun ROMs` | It is another game or another language version (French, Italian, Spanish are not supported). |
| a file is listed as `not a correct copy (damaged or modified)` | The game data differs from the original: a damaged copy (copy the cartridge again, clean the contacts) or an already patched/translated ROM. Padded or trimmed files are fine — the builder adjusts their size itself. |
| `missing Python packages` (manual way) | Run `python -m pip install -r requirements.txt` in the activated `.venv`. |
| `externally-managed-environment` (manual way) | Use the `.venv` commands from step 5 (or the easy way, which does this for you). |
| checksum differs from the reference build | Usually other package versions: install exactly `requirements.txt`. The game may still work. |
| the emulator cannot save / shows a save error | Set the save type to *Flash 128K* (1 Mbit) and restart. |

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
