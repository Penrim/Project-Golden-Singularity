"""File tour: log every file access while the merged ROM visits every map and every enemy group.

Breakpoints (bridge `calllog`, one line per new combination) on get_file (r0 = file number, lr = call site), the
unpack wrappers (r0 = source, r1 = destination) and the IWRAM copy routine 0x03001388 (r0 = destination,
r1 = source, r2 = size). Together with fileflow.py this gives, per file, how the game reads it.

  python filetour.py MERGED.gba ORIG_GS1.gba OUT.log
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
import fileflow, maptour, battletour, profiles

SHIFT = 0x01000000


def run(merged, orig, out):
    ff = fileflow.FileFlow(orig)
    hooks = [ff.getfile + 0x08000000 + SHIFT] + [o + 0x08000000 + SHIFT for o in ff.wrappers] + [0x03001388]
    log = os.path.abspath(out)
    if os.path.exists(log):
        os.remove(log)
    tag = os.path.splitext(os.path.basename(merged))[0] + "_files"
    field = maptour.field_state(merged, os.path.abspath(f"build/{tag}_field.ss"), True)
    world = battletour.worldmap_state(merged, field, os.path.abspath(f"build/{tag}_world.ss"))
    rets = profiles.profile_gs1(orig)["encounter_returns"]
    e = Emu.launch(merged); e.sock.settimeout(600)
    t0 = time.time()
    try:
        for h in hooks:
            e.cmd(f"calllog {h} {log}")
        for mp in range(201):
            e.load(field); e.wait(2)
            e.w16(maptour.MAP_VAR, mp); e.w16(maptour.WARP_TRIGGER, 1); e.wait(300)
            for k in ("DOWN", "RIGHT", "UP", "LEFT"):
                e.keys(k); e.wait(20)
            e.keys(); e.wait(20)
        print("maps done %.0fs" % (time.time() - t0), flush=True)
        for g in range(1, 256):
            e.load(world); e.wait(2)
            for a in rets:
                e.cmd(f"forceret {a + SHIFT} {g}")
            for k in range(6):
                e.keys("LEFT" if k % 2 else "RIGHT"); e.wait(25)
            e.keys(); e.wait(150)
            for k in range(25):
                e.press("A", hold=4, after=26)
        print("battles done %.0fs" % (time.time() - t0), flush=True)
    finally:
        e.proc.kill()


if __name__ == "__main__":
    run(*sys.argv[1:4])
