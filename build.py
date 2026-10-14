"""Golden Sun Collection - build the cartridge from your own two ROMs.

Easiest: put your ROM files (.gba or .zip) into the "roms" folder and double-click the launcher for your system
("Build (Windows).bat", "Build (macOS).command", "build-linux.sh"), or run:

    python build.py

It finds and checks the ROMs itself and builds every language for which both games are present.
Explicit files:

    python build.py --gs1 "Golden Sun (USA, Europe).gba" --tla "Golden Sun - The Lost Age (USA, Europe).gba"

The result is written next to this script as golden_sun_collection_<lang>.gba (or --out PATH).
Nothing from the games is included in this project: everything is read from the files you supply.
See README.md and BUILDING.md.
"""
import argparse, hashlib, os, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

VERSION = "1.1.1"

# Verified dumps (No-Intro). Other dumps of the same version may work but are untested.
SUPPORTED = {
    "5c4695205413df7db52b9a184815a07783999971": ("AGSE", "Golden Sun (USA, Europe)"),
    "b500663220cb9bf56b9f8e8c0c544f1d6fa3a824": ("AGFE", "Golden Sun - The Lost Age (USA, Europe)"),
    "c23ab91a39434623cf1a999f387d743ade1a22a6": ("AGSD", "Golden Sun (Germany)"),
    "7820b4c7ba9002b0e9be23a6f45a9ab204986438": ("AGFD", "Golden Sun - Die Vergessene Epoche (Germany)"),
    "42f3b262c16cfc5bde1fa2b25016fb74046de1b3": ("AGSF", "Golden Sun (France)"),
    "f14855c0f8c87a95cc52189e8e3b2bd9df186322": ("AGFF", "Golden Sun - L'Age Perdu (France)"),
    "ca45e04b26b2f040ac63e679a459d21869f5f28d": ("AGSI", "Golden Sun (Italy)"),
    "57f1d005666b81645e55412658427e27099c5907": ("AGFI", "Golden Sun - L'Era Perduta (Italy)"),
    "de0bdc889594b012cad213ca83707feb81ada28b": ("AGSS", "Golden Sun (Spain)"),
    "a2e3e80036195343c2713410ac14f4e329e3f40d": ("AGFS", "Golden Sun - La Edad Perdida (Spain)"),
}
PAIRS = {("AGSE", "AGFE"): "en", ("AGSD", "AGFD"): "de", ("AGSF", "AGFF"): "fr", ("AGSI", "AGFI"): "it",
         ("AGSS", "AGFS"): "es"}

# SHA-1 of the finished cartridge for each language (same on every system with the pinned requirements)
EXPECTED_OUTPUT = {
    "en": "5a8c4f2a5542a9fb745f21b8b4e804d4158043d1",
    "de": "9d87b87fa2437e19a6be82ff50fced38bbdc7321",
    "fr": "2de01797b30807c289f79e7cd7c4afa7026c7cb3",
    "it": "569f1cbbfc5f27cd53572bf8c5658af1a02470ae",
    "es": "d64dedca0a0c245f0315452eb4da8656df4b4c26",
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


ROM_SIZE = {**{gs1: 8 << 20 for gs1, tla in PAIRS}, **{tla: 16 << 20 for gs1, tla in PAIRS}}


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
    want = tuple(pair[0 if role == "gs1" else 1] for pair in PAIRS)
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


NAMES = {"AGSE": "Golden Sun (USA/Europe)", "AGFE": "The Lost Age (USA/Europe)",
         "AGSD": "Golden Sun (German)", "AGFD": "Die vergessene Epoche (German)",
         "AGSF": "Golden Sun (French)", "AGFF": "L'Age Perdu (French)",
         "AGSI": "Golden Sun (Italian)", "AGFI": "L'Era Perduta (Italian)",
         "AGSS": "Golden Sun (Spanish)", "AGFS": "La Edad Perdida (Spanish)"}
LANG_NAME = {"en": "English", "de": "German", "fr": "French", "it": "Italian", "es": "Spanish"}


def identify(path, tmp):
    """(game code, path of a verified copy) for a correct ROM file, else (None, reason). Never exits."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.lower().endswith(".gba")]
                if len(names) != 1:
                    return None, "zip file without exactly one .gba inside"
                data = z.read(names[0])
        else:
            data = open(path, "rb").read()
    except OSError as e:
        return None, f"cannot read ({e})"
    code = data[0xAC:0xB0].decode("ascii", "replace")
    if code not in ROM_SIZE:
        return None, "not one of the supported Golden Sun ROMs"
    for cand in normalise(data, code):
        if hashlib.sha1(cand).hexdigest() in SUPPORTED:
            out = os.path.join(tmp, code + ".gba")
            with open(out, "wb") as f:
                f.write(cand)
            return code, out
    return None, f"{NAMES[code]}, but not a correct copy (damaged or modified)"


VERBOSE = False


def build_one(gs1, tla, lang, out):
    import build_merge, contextlib, io
    print(f"building the {LANG_NAME[lang]} cartridge - this takes a few seconds")
    os.environ.setdefault("GSMERGE_PREBUILT", "1")      # players: precompiled runtime, no ARM toolchain
    if VERBOSE:
        build_merge.build(gs1, tla, out, lang)
    else:
        with contextlib.redirect_stdout(io.StringIO()):  # hide the builder's technical progress lines
            build_merge.build(gs1, tla, out, lang)
    sha = hashlib.sha1(open(out, "rb").read()).hexdigest()
    if sha == EXPECTED_OUTPUT[lang]:
        print(f"done: {out}\n  SHA-1 {sha} - identical to the reference build")
    else:
        print(f"done: {out}\n  SHA-1 {sha} (reference build: {EXPECTED_OUTPUT[lang]}; a different result usually "
              "means other package versions - see BUILDING.md)")
    return out


def auto(tmp):
    """Look for ROM files in roms/ and next to build.py; build every complete language pair."""
    folders = [os.path.join(HERE, "roms"), HERE]
    files = [os.path.join(d, f) for d in folders if os.path.isdir(d) for f in sorted(os.listdir(d))
             if f.lower().endswith((".gba", ".zip")) and not f.startswith("golden_sun_collection")]
    print("looking for your ROM files in the 'roms' folder" + (":" if files else " ..."))
    found = {}
    for f in files:
        code, info = identify(f, tmp)
        if code:
            found.setdefault(code, info)
            print(f"  OK  {os.path.basename(f)}  ->  {NAMES[code]}")
        else:
            print(f"  --  {os.path.basename(f)}  ({info})")
    built = []
    for (c1, c2), lang in PAIRS.items():
        if c1 in found and c2 in found:
            built.append(build_one(found[c1], found[c2], lang, os.path.join(HERE, f"golden_sun_collection_{lang}.gba")))
    if not built:
        need = []
        for (c1, c2), lang in PAIRS.items():
            if c1 in found or c2 in found:
                need.append(f"for the {LANG_NAME[lang]} version, add: {NAMES[c2] if c1 in found else NAMES[c1]}")
        print("\nNo cartridge built: both games of the same language are needed.")
        print("\n".join("  " + n for n in need) if need else
              "  Put your two ROM files (.gba or .zip) into the 'roms' folder, for example\n"
              "  Golden Sun (USA, Europe).gba  and  Golden Sun - The Lost Age (USA, Europe).gba")
        return 1
    print("\nPlay the .gba file in an emulator such as mGBA. Keep the .sav file: it holds the saves of both games.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Build the Golden Sun Collection cartridge from your own ROMs. "
                                 "Without --gs1/--tla the ROM files are searched in the 'roms' folder.")
    ap.add_argument("--gs1", help="Golden Sun ROM (.gba or .zip)")
    ap.add_argument("--tla", help="Golden Sun: The Lost Age ROM of the same language (.gba or .zip)")
    ap.add_argument("--out", help="output file (default: golden_sun_collection_<lang>.gba next to build.py)")
    ap.add_argument("--force", action="store_true", help="accept ROMs that are not the verified dumps (untested)")
    ap.add_argument("--verbose", action="store_true", help="show the builder's technical progress output")
    args = ap.parse_args()
    global VERBOSE
    VERBOSE = args.verbose
    print(f"Golden Sun Collection {VERSION}")
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required")
    try:
        import PIL, capstone  # noqa: F401
    except ImportError:
        sys.exit("missing Python packages - run:  python -m pip install -r requirements.txt")
    with tempfile.TemporaryDirectory() as tmp:
        if not args.gs1 and not args.tla:
            sys.exit(auto(tmp))
        if not (args.gs1 and args.tla):
            sys.exit("give both --gs1 and --tla, or neither (then the 'roms' folder is searched)")
        gs1 = read_rom(args.gs1, tmp)
        tla = read_rom(args.tla, tmp)
        print("checking ROMs")
        (c1, gs1), (c2, tla) = check(gs1, "gs1", args.force, tmp), check(tla, "tla", args.force, tmp)
        if (c1, c2) not in PAIRS:
            sys.exit(f"the two ROMs are different languages ({NAMES.get(c1, c1)} / {NAMES.get(c2, c2)}); "
                     "both must be the same language")
        lang = PAIRS[(c1, c2)]
        build_one(gs1, tla, lang, args.out or os.path.join(HERE, f"golden_sun_collection_{lang}.gba"))
    print("Use an emulator or flash cart with 128 KiB Flash saving (see README.md).")


if __name__ == "__main__":
    main()
