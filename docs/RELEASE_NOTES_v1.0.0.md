# Golden Sun Collection 1.0.0

Golden Sun and Golden Sun: The Lost Age on one cartridge, joined into one story — built from **your own** ROMs.

**This release contains no game data.** Download the source code below, install Python and the two packages, and
run `build.py` with your own dumps of both games (see README.md and BUILDING.md).

## Highlights
- Both complete games, unchanged, on one 32 MiB cartridge; English and German.
- New start screen with Golden Sun's original intro and music and a panorama from Golden Sun to The Lost Age.
- Separate saves for both games.
- Seamless chapter change: when Golden Sun ends, The Lost Age starts with your party imported automatically.

## Build
```
python -m pip install -r requirements.txt
python build.py --gs1 "Golden Sun (USA, Europe).gba" --tla "Golden Sun - The Lost Age (USA, Europe).gba"
```
Reference checksums of the finished cartridge (SHA-1): English `3fde5ab3ae785e78d4e5125a87e041955cdf1595`,
German `9d87b87fa2437e19a6be82ff50fced38bbdc7321`.

Unofficial fan project, not affiliated with Nintendo or Camelot. Please do not share built cartridges or ROMs.
