"""Playthrough replay test: the complete Golden Sun (USA) playthrough in data/playthrough/gs1_usa.movie, replayed on
the GS1 part of the merged cartridge and compared step by step with the original game (see docs/TESTING.md).

  python tools/playthrough/playthrough.py ref   GS1_USA.gba      [--out DIR] [--cpu SHARE]   (once, ~25-60 min)
  python tools/playthrough/playthrough.py check build/gsmerge_en.gba [--out DIR] [--cpu SHARE] (~25-60 min)
  python tools/playthrough/playthrough.py compare                [--out DIR]                 (report only)

ref     plays the movie on your original GS1 ROM and records the reference (DIR/ref.*).
check   replays it on the merged cartridge by game step up to the end of the credits, then lets the cartridge run on
        its own: clear-data save -> "Chapter 2" card -> The Lost Age. Then compares and writes DIR/report.txt.
compare compares DIR/ref.* with DIR/mrg.* again and rewrites the report.
Exit code 0 = PASS. Options for debugging: --save-every K (resume points DIR/mrg_ss_<step>), --from DIR/mrg_ss_<step>
(continue a check from such a point), --stop STEP. --cpu 4 runs the emulator uncapped (default: 60 % of one core).
"""
import argparse, glob, hashlib, os, re, shutil, struct, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
MOVIE = os.path.join(REPO, "data", "playthrough", "gs1_usa.movie")
BOOT_SAV = os.path.join(REPO, "data", "playthrough", "gs1_usa_boot.sav")
PLAYER = os.path.join(HERE, "player.lua")
RNG_ROUTINE = 0x08004458          # GS1 USA: the only code that writes the random seed (see player.lua)
STEP, CLEAR_FLAG = 0x03001E40, 0x0200044F
CARD_OFFSET, CARD_SIZE = 0x1B10000, 240 * 160 * 2   # merged cartridge: "Chapter 2" card (BGR555) at 0x09B10000
SNAP_EVERY = 600
REC = 8 + 0x1800                  # snapshot record: <I4 step, <I4 frame, 4 KiB EWRAM, 2 KiB IWRAM


def header():
    h = {}
    with open(MOVIE) as f:
        for line in f:
            if not line.startswith("#"): break
            m = re.match(r"#\s*(\w+):\s*(.*)", line)
            if m: h[m.group(1)] = m.group(2).strip()
    return h


def sha1(path):
    with open(path, "rb") as f: return hashlib.sha1(f.read()).hexdigest()


def prepare(rom, out, kind):
    """Copy the ROM into DIR next to the flash the movie starts from: the original game's flash held an old clear-data
    file in slot 1 (it changes the title menu, so the whole movie depends on it). The merged cartridge keeps GS1's
    save in flash bank 1 (bank 0 = The Lost Age, empty)."""
    os.makedirs(out, exist_ok=True)
    dst = os.path.join(out, kind + ".gba")
    if not os.path.exists(dst) or sha1(dst) != sha1(rom): shutil.copyfile(rom, dst)
    boot = open(BOOT_SAV, "rb").read()
    flash = boot if kind == "gs1" else b"\xff" * 0x10000 + boot
    for _ in range(20):                                 # a just-closed emulator may still hold the file
        try:
            with open(os.path.join(out, kind + ".sav"), "wb") as f: f.write(flash)
            break
        except OSError:
            time.sleep(0.5)
    else:
        sys.exit(f"cannot write {kind}.sav in {out} (is an emulator still running?)")
    return dst


def launch(rom, args, env):
    os.environ["GSMERGE_PORT"] = str(args.port)
    os.environ["GSMERGE_CPU"] = str(args.cpu)
    for k in [k for k in os.environ if k.startswith("PT_")]: del os.environ[k]
    os.environ.update({k: str(v) for k, v in env.items() if v is not None})
    import emu, cpucap                                  # emu reads GSMERGE_PORT at import
    emu.PORT = args.port
    return emu.Emu.launch(rom, script=PLAYER)


class Watch(threading.Thread):
    """Prints progress every minute and kills the emulator when its trace stops growing for `stall` seconds."""
    def __init__(self, trace, total, e, stall=300):
        super().__init__(daemon=True)
        self.trace, self.total, self.e, self.stall, self.stop = trace, total, e, stall, False

    def run(self):
        last, t_last = -1, time.time()
        while not self.stop:
            time.sleep(60)
            size = os.path.getsize(self.trace) if os.path.exists(self.trace) else 0
            step = None
            if size >= 14:
                with open(self.trace, "rb") as f:
                    f.seek(size - size % 14 - 14); step = struct.unpack("<HIII", f.read(14))[1]
            if size != last: last, t_last = size, time.time()
            print(time.strftime("%H:%M"), f"step {step} ({100 * (step or 0) / self.total:.0f} %)", flush=True)
            if time.time() - t_last > self.stall and not self.stop:
                print(f"STALL: no progress for {self.stall} s, stopping the emulator", flush=True)
                self.e.proc.kill(); return


def run_ref(args):
    h = header()
    if sha1(args.rom) != h["rom_sha1"]:
        sys.exit(f"{args.rom}: not Golden Sun (USA, Europe) (SHA-1 {h['rom_sha1']} expected)")
    rom = prepare(args.rom, args.out, "gs1")
    out = os.path.join(args.out, "ref")
    for f in glob.glob(out + "_*.png") + glob.glob(out + ".*"): os.remove(f)
    e = launch(rom, args, {"PT_RNG": RNG_ROUTINE, "PT_SAVE": args.save_every, "PT_STOP": args.stop})
    w = Watch(out + ".trace", 3490933, e); w.start()
    try:
        e.cmd("reset"); e.sock.settimeout(None)
        r = e.cmd(f"ref|{MOVIE}|{out}|{SNAP_EVERY}")
    finally:
        w.stop = True; e.close()
    print("reference:", r)
    scan = open(out + ".scanrng").read().split() if os.path.exists(out + ".scanrng") else []
    print("scenes with scanline-driven random calls:", sorted(int(x) for x in scan[0::2]))
    return 0 if r.startswith("done") else 1


def card_score(png, card):
    """Share of pixels whose colour matches the card image (within 24 per channel); the card itself scores 1.0,
    black screens and The Lost Age's first screens far below 0.9."""
    from PIL import Image
    shot = Image.open(png).convert("RGB").tobytes()
    hit = sum(1 for i in range(0, len(card), 3) if all(abs(card[i + k] - shot[i + k]) < 24 for k in range(3)))
    return hit / (len(card) // 3)


def run_check(args):
    h = header()
    ref = os.path.join(args.out, "ref")
    if not os.path.exists(ref + ".trace"): sys.exit("no reference yet: run 'playthrough.py ref GS1_USA.gba' first")
    rom = prepare(args.rom, args.out, "merged")
    out = os.path.join(args.out, "mrg")
    if not args.resume:
        for f in glob.glob(out + "_*.png") + glob.glob(out + ".*") + glob.glob(os.path.join(args.out, "handoff_*.png")):
            os.remove(f)
    stop = args.stop or int(h["credits_end_step"])
    e = launch(rom, args, {"PT_SCANRNG": ref + ".scanrng", "PT_SAVE": args.save_every, "PT_STOP": stop})
    w = Watch(out + ".trace", stop, e); w.start()
    try:
        if args.resume:
            e.sock.settimeout(None)
            r = e.cmd(f"alignstate|{ref}.trace|{out}|{SNAP_EVERY}|{os.path.abspath(args.resume)}")
        else:
            e.cmd("reset")
            pre = [0] * 256
            for f in (121, 122, 241, 242): pre[f - 1] = 1
            with open(ref + ".trace", "rb") as f: raw = f.read(14 * 4)
            seq = pre + [struct.unpack_from("<H", raw, 14 * i)[0] for i in range(4)]
            i = 0
            while i < len(seq):
                j = i
                while j < len(seq) and seq[j] == seq[i]: j += 1
                e.cmd(f"keys {seq[i]}"); e.cmd(f"wait {j - i}"); i = j
            e.sock.settimeout(None)
            r = e.cmd(f"align|{ref}.trace|{out}|{SNAP_EVERY}|4")
        w.stop = True
        print("replay:", r, flush=True)
        handoff = []
        if r.startswith("done") and not args.stop:      # chapter change, no input from here on
            e.sock.settimeout(120)
            e.cmd("keys 0")
            for i in range(1, 41):
                p = os.path.join(args.out, f"handoff_{i:02d}.png")
                e.cmd("wait 30"); e.cmd(f"shot|{os.path.abspath(p)}")
                handoff.append((p, int(e.cmd(f"r32 {CLEAR_FLAG & ~3}")) >> (8 * (CLEAR_FLAG & 3)) & 0xFF,
                                int(e.cmd(f"r32 {STEP}"))))
    finally:
        w.stop = True; e.close()
    with open(os.path.join(args.out, "handoff.txt"), "w") as f:
        for p, flag, step in handoff: f.write(f"{os.path.basename(p)} {flag} {step}\n")
    return report(args)


def snaps(path):
    out = {}
    if not os.path.exists(path): return out
    raw = open(path, "rb").read()
    for i in range(0, len(raw) - REC + 1, REC):
        g, f = struct.unpack_from("<II", raw, i)
        out[g] = (f, struct.unpack_from("<%dI" % (0x1800 // 4), raw, i + 8))
    return out


def report(args):
    from PIL import Image, ImageChops
    h = header(); d = args.out
    ref, mrg = os.path.join(d, "ref"), os.path.join(d, "mrg")
    lines, ok = [], True
    log = open(mrg + ".log").read().splitlines() if os.path.exists(mrg + ".log") else []
    end = log[-1] if log else "no replay log"
    goal = args.stop or int(h["credits_end_step"])
    m = re.match(r"done \d+ (\d+)", end)
    reached = bool(m) and int(m.group(1)) >= goal
    ok &= reached
    lines.append(f"replay: {end} -> {'reached' if reached else 'DID NOT REACH'} step {goal}")
    rng = [l for l in log if l.startswith("rng ")]
    fixes = [l for l in log if l.startswith("rngfix")]
    ok &= not rng
    per_scene = {}
    for l in fixes:
        sc = re.search(r"scene (\d+)", l).group(1); per_scene[sc] = per_scene.get(sc, 0) + 1
    lines.append(f"random seed after every step: {len(rng)} mismatches (first: {rng[0] if rng else '-'}); "
                 f"{len(fixes)} realignments in scanline-RNG scenes {per_scene or ''}; "
                 f"{sum(1 for l in log if l.startswith('vbl'))} VBlank-counter corrections after loads")
    A, B = snaps(ref + ".snap"), snaps(mrg + ".snap")
    common = sorted(g for g in set(A) & set(B) if g <= goal)
    bad = []
    for g in common:
        diff = [(0x02000000 + 4 * i if i < 0x400 else 0x03001800 + 4 * (i - 0x400), x, y)
                for i, (x, y) in enumerate(zip(A[g][1], B[g][1]))
                if x != y and not (0x09000000 <= y < 0x0A000000 and y - 0x01000000 == x)]   # relocated ROM pointer
        if diff: bad.append((g, diff))
    ok &= not bad and (bool(args.resume) or len(common) >= goal // SNAP_EVERY - 1)
    lines.append(f"RAM snapshots: {len(common)} compared, {len(bad)} differ")
    for g, diff in bad[:20]:
        lines.append(f"  step {g}: " + ", ".join(f"{a:08x} {x:08x}/{y:08x}" for a, x, y in diff[:6]))
    # screens: informational (mid-frame update timing makes a few differ for a step or three; RAM decides)
    shots = {}
    for p in glob.glob(ref + "_*.png"):
        g = int(re.search(r"_(\d+)\.png$", p).group(1)); q = f"{mrg}_{g:07d}.png"
        if g <= goal and os.path.exists(q):
            a, b = Image.open(p).convert("RGB"), Image.open(q).convert("RGB")
            shots[g] = ImageChops.difference(a, b).getbbox()
    base = sorted(g for g in shots if g % SNAP_EVERY == 0)
    pers = [g for g in base if shots[g] and all(shots.get(g + k) for k in (1, 2))]
    brief = [g for g in base if shots[g] and g not in pers]
    lines.append(f"screens: {len(base)} steps compared, {len(pers)} differ for 3 steps, {len(brief)} for 1-2 steps "
                 f"(review side by side in {os.path.join(d, 'diffs')})")
    os.makedirs(os.path.join(d, "diffs"), exist_ok=True)
    for g in pers:
        a, b = Image.open(f"{ref}_{g:07d}.png").convert("RGB"), Image.open(f"{mrg}_{g:07d}.png").convert("RGB")
        c = Image.new("RGB", (484, 160), (0, 0, 255)); c.paste(a, (0, 0)); c.paste(b, (244, 0))
        c.save(os.path.join(d, "diffs", f"step_{g:07d}.png"))
        lines.append(f"  step {g}: {[shots.get(g + k) for k in (0, 1, 2)]}")
    hf = os.path.join(d, "handoff.txt")
    if os.path.exists(hf) and not args.stop:
        rows = [l.split() for l in open(hf).read().splitlines()]
        rom = open(os.path.join(d, "merged.gba"), "rb").read()[CARD_OFFSET:CARD_OFFSET + CARD_SIZE]
        card = bytearray()
        for i in range(0, CARD_SIZE, 2):                # BGR555 -> RGB888 like mGBA's screenshots
            v = rom[i] | rom[i + 1] << 8
            card += bytes(((v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3))
        scores = [(row[0], card_score(os.path.join(d, row[0]), card), int(row[1]), int(row[2])) for row in rows]
        seen = [s for s in scores if s[1] >= 0.98]
        restarted = any(s[3] == 0 for s in scores)
        later = [s for s in scores if s[3] == 0]
        tla = bool(later) and later[-1][1] < 0.95       # something other than the card on screen at the end
        hand_ok = len(seen) >= 2 and any(s[2] == 1 for s in scores[:len(scores) // 2]) and restarted and tla
        ok &= hand_ok
        lines.append(f"chapter change: card visible in {len(seen)} of {len(scores)} screens (every 0.5 s), "
                     f"clear-data flag set: {any(s[2] == 1 for s in scores)}, GS1 left (step counter 0): {restarted}, "
                     f"next screen after the card: {'yes' if tla else 'NO'} -> {'ok' if hand_ok else 'FAILED'}")
    elif not args.stop:
        ok = False; lines.append("chapter change: not reached")
    lines.insert(0, f"RESULT: {'PASS' if ok else 'FAIL'}  (movie {h['frames']} frames, "
                    f"merged {os.path.basename(args.rom or 'merged.gba')})")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(d, "report.txt"), "w") as f: f.write(text + "\n")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["ref", "check", "compare"])
    ap.add_argument("rom", nargs="?")
    ap.add_argument("--out", default=os.path.join(REPO, "build", "playthrough"))
    ap.add_argument("--cpu", type=float, default=float(os.environ.get("GSMERGE_CPU", "0.6")),
                    help="CPU share of one core for the emulator (default 0.6; 4 = uncapped)")
    ap.add_argument("--port", type=int, default=61344)
    ap.add_argument("--save-every", type=int, help="resume point every K game steps")
    ap.add_argument("--from", dest="resume", help="check: continue from DIR/mrg_ss_<step> (without .ss)")
    ap.add_argument("--stop", type=int, help="stop at this game step (partial run, no chapter-change check)")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)
    if args.mode in ("ref", "check") and not args.rom: ap.error("ROM path missing")
    if args.mode == "ref": sys.exit(run_ref(args))
    if args.mode == "check": sys.exit(run_check(args))
    sys.exit(report(args))


if __name__ == "__main__":
    main()
