"""Drive mGBA through tools/bridge.lua (start with Emu.launch(rom))."""
import os, socket, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
MGBA = os.path.join(HERE, "mgba-dev", "mGBA.exe")
PORT = int(os.environ.get("GSMERGE_PORT", "61337"))   # bridge.lua reads the same variable (parallel runs)

KEY = {"A": 1, "B": 2, "SELECT": 4, "START": 8, "RIGHT": 16, "LEFT": 32, "UP": 64, "DOWN": 128, "R": 256, "L": 512}


class Emu:
    def __init__(self, proc, sock):
        self.proc, self.sock, self.f = proc, sock, sock.makefile("r")

    @classmethod
    def launch(cls, rom, timeout=90):                  # capped emulators start slower under load
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # SW_SHOWMINNOACTIVE: don't steal focus from the user
        proc = subprocess.Popen(startupinfo=si, args=[MGBA, "--script", os.path.join(HERE, "bridge.lua"), "-C", "pauseOnFocusLost=0",
                                 "-C", "audioSync=0", "-C", "videoSync=0", "-C", "fpsTarget=600",
                                 "-C", "mute=1", "-C", "volume=0", rom])   # tests run silent (no fast-forward noise)
        try:                                          # at most GSMERGE_CPU (default 60 %) of one core, low priority
            import cpucap
            cpucap.cap(proc.pid)
        except OSError:
            pass
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
                s.settimeout(120)
                e = cls(proc, s)
                if e.cmd("ping") == "pong":
                    return e
            except OSError:
                time.sleep(0.5)
        proc.kill()
        raise RuntimeError("mGBA bridge did not come up")

    def cmd(self, line):
        self.sock.sendall((line + "\n").encode())
        return self.f.readline().strip()

    def wait(self, n): return self.cmd(f"wait {n}")

    def to_menu(self):
        """Merged cartridge after reset: skip the GS1 intro replay (START) and wait until the start menu has
        faded in, so the next key press goes to the menu."""
        self.wait(30)
        self.press("START", hold=4, after=10)
        self.wait(70)

    def keys(self, *names): return self.cmd(f"keys {sum(KEY[n] for n in names)}")

    def press(self, *names, hold=4, after=10):
        self.keys(*names); self.wait(hold); self.keys(); self.wait(after)

    def r8(self, a): return int(self.cmd(f"r8 {a}"))
    def r16(self, a): return int(self.cmd(f"r16 {a}"))
    def r32(self, a): return int(self.cmd(f"r32 {a}"))
    def rr(self, a, n): return bytes.fromhex(self.cmd(f"rr {a} {n}"))
    def w8(self, a, v): return self.cmd(f"w8 {a} {v}")
    def w16(self, a, v): return self.cmd(f"w16 {a} {v}")
    def w32(self, a, v): return self.cmd(f"w32 {a} {v}")
    def dumpmem(self, a, n, path): return self.cmd(f"dumpmem {a} {n} {os.path.abspath(path)}")
    def shot(self, path): return self.cmd(f"shot {os.path.abspath(path)}")
    def save(self, path): return self.cmd(f"save {os.path.abspath(path)}")
    def load(self, path): return self.cmd(f"load {os.path.abspath(path)}")

    def watch(self, lo, hi): return self.cmd(f"watch {lo} {hi}")

    def hits(self):
        """{pc: (count, regs)} of watchpoint hits since the last call."""
        out = {}
        for item in filter(None, self.cmd("hits").split(";")):
            pc, n, regs = item.split(":", 2)
            out[int(pc, 16)] = (int(n), regs)
        return out

    def close(self):
        try: self.sock.close()
        finally: self.proc.kill()
