"""Start-menu test: empty cart, TLA save -> Continue goes to TLA, GS1 save only -> Continue goes to GS1.

Usage: python test_menu.py build/gsmerge.gba OUTDIR [GS1_BANK.sav]
(GS1_BANK.sav: a 64 KiB GS1 save of the same language; default build/tour/gs1_backup.sav)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TOUR = os.path.join(os.path.dirname(HERE), "build", "tour")
BLANK = b"\xff" * 0x10000


def write_sav(path, data):
    for _ in range(10):
        try:
            open(path, "wb").write(data)
            return
        except OSError:
            time.sleep(1)
    raise RuntimeError("could not write " + path)


def boot(rom, presses):
    e = Emu.launch(rom); e.sock.settimeout(30); e.cmd("reset")
    e.to_menu()
    return e


def main(rom, out, gs1_sav=os.path.join(TOUR, "gs1_backup.sav")):
    os.makedirs(out, exist_ok=True)
    sav = os.path.splitext(rom)[0] + ".sav"
    shots = []

    # 1) empty cartridge: menu without Continue; choose Chapter 2 and make a TLA save
    write_sav(sav, BLANK + BLANK)
    e = boot(rom, 0)
    p = os.path.join(out, "1_menu_empty.png"); e.shot(p); shots.append(p)
    e.press("DOWN", after=20); e.press("A", after=30)
    for k in range(120):
        e.press("START" if k % 4 == 0 else "A", hold=6, after=40)
    for k in range(400):
        e.press("A", hold=4, after=26)
    for _ in range(6):
        e.press("B", after=15)
    e.wait(30); e.press("START", after=40)
    for _ in range(4):
        e.press("A", after=60)
    p = os.path.join(out, "1_tla_saved.png"); e.shot(p); shots.append(p)
    e.wait(300); e.close()
    tla_bank = open(sav, "rb").read()[:0x10000]

    # 2) TLA save present: Continue must start The Lost Age
    e = boot(rom, 0)
    p = os.path.join(out, "2_menu_continue.png"); e.shot(p); shots.append(p)
    e.press("A", after=30); e.wait(500)
    p = os.path.join(out, "2_after_continue.png"); e.shot(p); shots.append(p)
    print("continue with TLA save -> game code", e.rr(0x080000AC, 4))
    e.close()

    # 3) only a GS1 save: Continue must start Golden Sun
    write_sav(sav, BLANK + open(gs1_sav, "rb").read())
    e = boot(rom, 0)
    p = os.path.join(out, "3_menu_gs1only.png"); e.shot(p); shots.append(p)
    e.press("A", after=30); e.wait(500)
    p = os.path.join(out, "3_after_continue.png"); e.shot(p); shots.append(p)
    e.close()

    write_sav(sav, tla_bank + BLANK)
    c = Image.new("RGB", (240 * 3, 160 * 2))
    for i, p in enumerate(shots):
        c.paste(Image.open(p), (240 * (i % 3), 160 * (i // 3)))
    c.save(os.path.join(out, "menu_sheet.png"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
