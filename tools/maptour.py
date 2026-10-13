"""Map tour: warp to every Golden Sun 1 map in the original and in the merged ROM, compare, log stray reads.

Warp mechanism (from CodeBreaker codes): u16 map -> 0x02000400, u16 1 -> 0x02030170.
Usage: python maptour.py ORIG.gba MERGED.gba OUTDIR [first last]
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from difftest import default_script
from PIL import Image, ImageChops

MAP_VAR, WARP_TRIGGER = 0x02000400, 0x02030170
SETTLE = 300


def field_state(rom, path, merged):
    """Boot to the Vale field and save a state there (cached)."""
    if os.path.exists(path):
        return path
    e = Emu.launch(rom); e.sock.settimeout(30); e.cmd("reset")
    if merged:
        e.to_menu(); e.press("A", after=30)
    for keys, frames in default_script():
        e.keys(*keys); e.wait(frames)
    e.keys()
    for _ in range(6):
        e.press("B", after=15)
    e.wait(30)
    e.save(path)
    e.close()
    return path


def tour(rom, state, outdir, maps, watch):
    """Visit each map; a crash/hang on one map is recorded and the emulator is restarted for the next."""
    os.makedirs(outdir, exist_ok=True)
    result = {}
    e = None
    for m in maps:
        try:
            if e is None:
                e = Emu.launch(rom); e.sock.settimeout(15)
            e.load(state); e.wait(2)
            if watch:
                e.cmd(f"acclog {watch[0]} {watch[1]}")
            e.w16(MAP_VAR, m); e.w16(WARP_TRIGGER, 1)
            e.wait(SETTLE)
            for d in ("DOWN", "RIGHT", "UP", "LEFT"):  # walk a little so map scripts / NPC code run
                e.keys(d); e.wait(20)
            e.keys(); e.wait(30)
            e.shot(os.path.join(outdir, f"{m:03d}.png"))
            result[m] = [l for l in e.cmd("accdump").split(";") if l] if watch else []
        except (OSError, ValueError):
            result[m] = ["CRASH"]
            print(f"  map {m}: crash/hang")
            if e:
                e.close()
            e = None
    if e:
        e.close()
    return result


def diff_ratio(a, b):
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    d = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > 24 else 0)
    return sum(1 for v in d.getdata() if v) / (240 * 160)


if __name__ == "__main__":
    orig, merged, out = sys.argv[1:4]
    first, last = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (0, 200)
    maps = range(first, last + 1)
    so = field_state(orig, os.path.join(out, "orig_field.ss"), False)
    sm = field_state(merged, os.path.join(out, "merged_field.ss"), True)
    tour(orig, so, os.path.join(out, "orig"), maps, None)
    res = tour(merged, sm, os.path.join(out, "merged"), maps, (0x08000000, 0x08FFFFFF))
    report = {}
    for m in maps:
        a, b = os.path.join(out, "orig", f"{m:03d}.png"), os.path.join(out, "merged", f"{m:03d}.png")
        r = diff_ratio(a, b) if os.path.exists(a) and os.path.exists(b) else 1.0
        report[m] = {"diff": round(r, 4), "stray": res[m][:10]}
    json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=1)
    bad_stray = [m for m in maps if report[m]["stray"]]
    big_diff = [m for m in maps if report[m]["diff"] > 0.05]
    print(f"maps {first}-{last}: stray reads on {len(bad_stray)} maps {bad_stray[:30]}")
    print(f"screens differing >5%: {len(big_diff)} {big_diff[:40]}")
