"""Battle tour: force every enemy group in the original and the merged ROM, auto-fight, compare, log stray reads.

Encounter forcing: GS1 0x0808AE74 returns the encounter's enemy group (0 = none); its two wrappers return to
0x0808B03E / 0x0808B056. A breakpoint there sets r0 = group while walking on the world map.
Usage: python battletour.py ORIG.gba MERGED.gba OUTDIR [first last]
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
import maptour
import profiles

RET_ADDRS = (0x0808B03E, 0x0808B056)
SHIFT = 0x01000000
WORLD_MAP = 2


def worldmap_state(rom, field_state, path):
    if os.path.exists(path):
        return path
    e = Emu.launch(rom); e.sock.settimeout(15)
    e.load(field_state); e.wait(2)
    e.w16(maptour.MAP_VAR, WORLD_MAP); e.w16(maptour.WARP_TRIGGER, 1)
    e.wait(300)
    e.save(path); e.close()
    return path


def tour(rom, state, outdir, groups, shift, watch, ret_addrs=RET_ADDRS):
    os.makedirs(outdir, exist_ok=True)
    result, e = {}, None
    for grp in groups:
        try:
            if e is None:
                e = Emu.launch(rom); e.sock.settimeout(15)
            e.load(state); e.wait(2)
            if watch:
                e.cmd(f"acclog {watch[0]} {watch[1]}")
            for a in ret_addrs:
                e.cmd(f"forceret {a + shift} {grp}")
            for k in range(6):                     # walk until the forced encounter fires
                e.keys("LEFT" if k % 2 else "RIGHT"); e.wait(25)
            e.keys(); e.wait(150)
            e.shot(os.path.join(outdir, f"{grp:03d}_a.png"))
            for k in range(40):                    # fight: confirm every menu with A
                e.press("A", hold=4, after=26)
            e.shot(os.path.join(outdir, f"{grp:03d}_b.png"))
            result[grp] = [l for l in e.cmd("accdump").split(";") if l] if watch else []
        except (OSError, ValueError):
            result[grp] = ["CRASH"]
            print(f"  group {grp}: crash/hang")
            if e:
                e.close()
            e = None
    if e:
        e.close()
    return result


if __name__ == "__main__":
    orig, merged, out = sys.argv[1:4]
    first, last = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (1, 255)
    groups = range(first, last + 1)
    so = maptour.field_state(orig, os.path.join(out, "orig_field.ss"), False)
    sm = maptour.field_state(merged, os.path.join(out, "merged_field.ss"), True)
    wo = worldmap_state(orig, so, os.path.join(out, "orig_world.ss"))
    wm = worldmap_state(merged, sm, os.path.join(out, "merged_world.ss"))
    rets = profiles.profile_gs1(orig)["encounter_returns"]
    ro = tour(orig, wo, os.path.join(out, "borig"), groups, 0, None, rets)
    rm = tour(merged, wm, os.path.join(out, "bmerged"), groups, SHIFT, (0x08000000, 0x08FFFFFF), rets)
    report = {}
    for g in groups:
        diffs = []
        for s in ("a", "b"):
            pa = os.path.join(out, "borig", f"{g:03d}_{s}.png")
            pb = os.path.join(out, "bmerged", f"{g:03d}_{s}.png")
            diffs.append(round(maptour.diff_ratio(pa, pb), 4) if os.path.exists(pa) and os.path.exists(pb) else 1.0)
        report[g] = {"orig": ro[g][:1], "stray": rm[g][:10], "diff": diffs}
    json.dump(report, open(os.path.join(out, "battle_report.json"), "w"), indent=1)
    crash_m = [g for g in groups if rm[g] == ["CRASH"]]
    crash_o = [g for g in groups if ro[g] == ["CRASH"]]
    stray = [g for g in groups if rm[g] and rm[g] != ["CRASH"]]
    big = [g for g in groups if report[g]["diff"][0] > 0.05]
    print(f"groups {first}-{last}: crashes merged {crash_m[:30]} (orig {crash_o[:30]})")
    print(f"stray reads: {stray[:30]}")
    print(f"battle-start screens differing >5%: {len(big)} {big[:40]}")
