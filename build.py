"""Golden Sun Collection - build the cartridge from your own two ROMs.

    python build.py --gs1 "Golden Sun (USA, Europe).gba" --tla "Golden Sun - The Lost Age (USA, Europe).gba"

The ROMs may also be given as .zip files. Both must be the same language; the language is detected from the ROMs.
The result is written next to this script as golden_sun_collection_<lang>.gba (or --out PATH).
Nothing from the games is included in this project: everything is read from the files you supply.
See README.md and BUILDING.md.
"""
import argparse, hashlib, os, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

VERSION = "1.0.0"

# Verified dumps (No-Intro). Other dumps of the same version may work but are untested.
SUPPORTED = {
    "5c4695205413df7db52b9a184815a07783999971": ("AGSE", "Golden Sun (USA, Europe)"),
    "b500663220cb9bf56b9f8e8c0c544f1d6fa3a824": ("AGFE", "Golden Sun - The Lost Age (USA, Europe)"),
    "c23ab91a39434623cf1a999f387d743ade1a22a6": ("AGSD", "Golden Sun (Germany)"),
    "7820b4c7ba9002b0e9be23a6f45a9ab204986438": ("AGFD", "Golden Sun - Die Vergessene Epoche (Germany)"),
}
PAIRS = {("AGSE", "AGFE"): "en", ("AGSD", "AGFD"): "de"}

# SHA-1 of the finished cartridge for each language (same on every system with the pinned requirements)
EXPECTED_OUTPUT = {
    "en": "3fde5ab3ae785e78d4e5125a87e041955cdf1595",
    "de": "9d87b87fa2437e19a6be82ff50fced38bbdc7321",
}


def read_rom(path, tmp):
    """Path to a plain .gba file (a .zip is unpacked into tmp)."""
    if not os.path.exists(path):
        sys.exit(f"file not found: {path}")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".gba")]
            if len(names) != 1:
                sys.exit(f"{path}: expected exactly one .gba file in the zip, found {len(names)}")
            out = os.path.join(tmp, os.path.basename(names[0]))
            with open(out, "wb") as f:
                f.write(z.read(names[0]))
            return out
    return path


ROM_SIZE = {"AGSE": 8 << 20, "AGSD": 8 << 20, "AGFE": 16 << 20, "AGFD": 16 << 20}


def normalise(data, code):
    """Some dumpers pad the file with empty space or cut empty space off the end. The game data is the same, so
    bring the file to the cartridge's real size first: trim a padded tail, or pad a trimmed file with 0xFF/0x00."""
    size = ROM_SIZE[code]
    tail = data[size:]
    if len(data) > size and (not tail.strip(bytes([0xFF])) or not tail.strip(bytes([0x00]))):
        return [data[:size]]
    if len(data) < size:
        return [data + bytes([fill]) * (size - len(data)) for fill in (0xFF, 0x00)]
    return [data]


def check(path, role, force, tmp):
    """Returns (game code, path of a verified copy to build from)."""
    data = open(path, "rb").read()
    code = data[0xAC:0xB0].decode("ascii", "replace")
    want = ("AGSE", "AGSD") if role == "gs1" else ("AGFE", "AGFD")
    if code not in want:
        sys.exit(f"{path}: this is not {'Golden Sun' if role == 'gs1' else 'Golden Sun: The Lost Age'} "
                 f"(game code {code!r}; expected one of {', '.join(want)})")
    for cand in normalise(data, code):
        sha = hashlib.sha1(cand).hexdigest()
        if sha in SUPPORTED:
            note = "" if cand == data else f" (file size adjusted from {len(data)} to {len(cand)} bytes)"
            print(f"  {SUPPORTED[sha][1]}: verified dump{note}")
            if cand != data:
                path = os.path.join(tmp, role + "_normalised.gba")
                with open(path, "wb") as f:
                    f.write(cand)
            return code, path
    sha = hashlib.sha1(data).hexdigest()
    if force:
        print(f"  WARNING {path}: SHA-1 {sha} is not a known good dump; continuing because of --force")
        return code, path
    sys.exit(f"{path}: SHA-1 {sha} does not match the correct copy of this game "
             "(damaged or modified dump, or another game version? See README.md, 'Which ROMs'). "
             "Use --force to try anyway.")


def main():
    ap = argparse.ArgumentParser(description="Build the Golden Sun Collection cartridge from your own ROMs.")
    ap.add_argument("--gs1", required=True, help="Golden Sun ROM (.gba or .zip)")
    ap.add_argument("--tla", required=True, help="Golden Sun: The Lost Age ROM of the same language (.gba or .zip)")
    ap.add_argument("--out", help="output file (default: golden_sun_collection_<lang>.gba next to build.py)")
    ap.add_argument("--force", action="store_true", help="accept ROMs that are not the verified dumps (untested)")
    args = ap.parse_args()
    print(f"Golden Sun Collection {VERSION}")
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required")
    try:
        import PIL, capstone  # noqa: F401
    except ImportError:
        sys.exit("missing Python packages - run:  python -m pip install -r requirements.txt")
    import build_merge

    with tempfile.TemporaryDirectory() as tmp:
        gs1 = read_rom(args.gs1, tmp)
        tla = read_rom(args.tla, tmp)
        print("checking ROMs")
        (c1, gs1), (c2, tla) = check(gs1, "gs1", args.force, tmp), check(tla, "tla", args.force, tmp)
        pair = (c1, c2)
        if pair not in PAIRS:
            sys.exit(f"the two ROMs are different languages ({pair[0]} / {pair[1]}); both must be USA/Europe "
                     "or both German")
        lang = PAIRS[pair]
        out = args.out or os.path.join(HERE, f"golden_sun_collection_{lang}.gba")
        print(f"building ({'English' if lang == 'en' else 'German'}) - this takes a few seconds")
        os.environ.setdefault("GSMERGE_PREBUILT", "1")      # players: precompiled runtime, no ARM toolchain
        build_merge.build(gs1, tla, out, lang)
    sha = hashlib.sha1(open(out, "rb").read()).hexdigest()
    if sha == EXPECTED_OUTPUT[lang] and not args.force:
        print(f"done: {out}\n  SHA-1 {sha} - identical to the reference build")
    else:
        print(f"done: {out}\n  SHA-1 {sha} (reference build: {EXPECTED_OUTPUT[lang]}; a different result usually "
              "means other package versions - see BUILDING.md)")
    print("Use an emulator or flash cart with 128 KiB Flash saving (see README.md).")


if __name__ == "__main__":
    main()
