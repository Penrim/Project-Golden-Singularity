# Testing and debugging

The project is verified **automatically**: no manual playtesting is needed for regression checks. Tests drive the
mGBA development build through a Lua bridge and compare the merged cartridge with the original GS1.

## 1. The emulator bridge

`tools/emu.py` starts `tools/mgba-dev/mGBA.exe --script tools/bridge.lua <rom>` (window minimised, no focus
stealing) and connects to TCP port **61337**. Commands are executed inside mGBA's frame callback, so the game
runs between commands; `wait N` advances N frames.

| Python (`Emu`) | Bridge command | Meaning |
|---|---|---|
| `wait(n)`, `keys(...)`, `press(key)` | `wait`, `keys MASK` | frames / hold keys (A=1 B=2 Select=4 Start=8 Right=16 Left=32 Up=64 Down=128 R=256 L=512) |
| `r8/r16/r32`, `rr(addr, n)`, `w8/w16/w32` | `r8` … `w32` | memory |
| `dumpmem(addr, n, path)` | `dumpmem` | dump memory to a file in one frame (consistent snapshot) |
| `shot(path)`, `save(path)`, `load(path)` | `shot`, `save`, `load` | screenshot / savestate |
| `cmd("reset")`, `cmd("pc")`, `cmd("regs")` | | reset / registers |
| `watch(lo, hi)` + `hits()` | `watch`, `hits` | read watchpoint, first hit per frame (cheap) |
| | `acclog LO HI` / `accdump` | log up to 400 reads with pc, address, value |
| | `acclogf LO HI PATH` | same, streamed to a file (survives crashes) |
| | `acclogwf LO HI PATH` | write log to a file (frame, pc, lr, address, new value; up to 50 000 entries) — used for write-only IO registers |
| `to_menu()` | | merged ROM after reset: START skips the intro replay, waits until the start menu is shown |
| | `record N PREFIX` | dump VRAM/palette/OAM/IO + screenshot on each of the next N frames (`PREFIX<frame>_<region>.bin`); used for the intro replay |
| | `bplog ADDR PATH` | append registers to a file every time ADDR executes |
| | `watchwidth LIST OUT` | log the access width of reads of listed words (LIST path without spaces) |
| | `ptrprobe LIST LO HI` / `ptrdump PATH` | pointer probe (see TECHNICAL "Relocation false positives"); LIST path without spaces |
| | `bponce ADDR PATH` | registers (incl. r12, sp, lr, pc, cpsr) at the first hit only — safe inside crash loops |
| | `bpwrite ADDR WADDR VALUE` | at ADDR (once) write a u32 |
| | `forceret ADDR VALUE` | at ADDR (once, if r0 == 0) set r0 = VALUE — used to force battles |
| | `callafter FUNC TARGET` | after FUNC returns, call TARGET (experimental) |
| | `watchall` / `unwatchall` | counting watchpoint (expensive, few frames only) |

Watchpoint callbacks receive an `info` table: `address, width, oldValue, newValue, accessType, segment`.

**Gotchas**
- CPU: every emulator started by `emu.py` is capped at `GSMERGE_CPU` of one core (default 0.6 = 60 %) with a
  Windows job object and runs at below-normal priority (`tools/cpucap.py`; `python tools/cpucap.py PID` caps a
  running one). Tests take correspondingly longer but never saturate a core.
- Parallel runs: set `GSMERGE_PORT` (e.g. 61351, 61352, ...) per test process; `emu.py` and `bridge.lua`
  both read it (default 61337). Used to probe/test several languages at once.
- "bridge did not come up" with the Scripting window showing `bridge.lua:370: attempt to index a nil value (local
  'server')`: the port cannot be bound. WSL/Hyper-V reserve TCP port ranges dynamically (2026-10-15: 61358-61957,
  which covered the earlier test ports 61431+); check with `netsh interface ipv4 show excludedportrange
  protocol=tcp` and pick free ports (61341-61345 were free).
- One bridge per port; a leftover mGBA keeps its port busy ("bridge did not come up"). Kill it by path:
  `Get-Process mGBA | ? { $_.Path -like '*GoldenSunMerge*' } | Stop-Process -Force`.
- An mGBA crash dialog ("Jumped to invalid address …") pauses emulation → socket timeout. Tests treat a timeout as
  a crash and restart the emulator.
- Savestates do not restore the flash bank selection (see TECHNICAL §2).
- Never write literal newlines into Lua/C strings from Python heredocs; files created with the Write tool use CRLF
  (Python `str.replace` with `"\n"` patterns silently misses — edit with the Edit tool instead).

## 2. Test scripts

| Script | Covers | Expected result (2026-10-12) |
|---|---|---|
| `maptour.py ORIG MERGED OUT [first last]` | warps to all 201 GS1 maps in both ROMs, walks, screenshots, stray-read watch 0x08000000–0x08FFFFFF | 0 crashes, 0 stray reads; ~15 screens differ by timing only (NPC/camera positions) |
| `battletour.py ORIG MERGED OUT [first last]` | forces all 255 enemy groups on the world map (`forceret`), auto-fights with A | 0 crashes, 0 stray reads; ~42 battle starts differ only by random formation |
| `test_saves.py MERGED OUT` | save in GS1, save in TLA, check banks, reload both | GS1 → bank 1, TLA → bank 0, no interference, both reload |
| `test_menu.py MERGED OUT [GS1_BANK.sav]` | start menu with no save / TLA save / GS1-only save (GS1 bank of the same language; default `build/tour/gs1_backup.sav`) | 2 entries / Continue → TLA / Continue → GS1 |
| `test_transition.py MERGED OUT [DEMO.ss1]` | empty cart → Chapter 1 → simulated end of credits → (saves the demo state) → Isaac renamed "Alex" → clear save, chapter card, TLA new game | prints `RESULT: PASS`: "Alex" in TLA RAM (0x02000520), bank 1 holds clear data |
| `pointer_probe.py run MERGED ORIG OUT [states]` + `list ORIG OUT [OTHER_GS1 ...]` | which relocated words the game reads byte-wise (data, not pointers) | writes `data/reloc_exclude_<code>.txt`; rebuild afterwards (~25 min) |
| `difftest.py ORIG TEST OUT` | same scripted input on two ROMs | (early tool; screens differ by timing because recompressed map code decompresses at a different speed) |

Run the tours per language: the original GS1 of that language is the reference (e.g. `"Golden Sun (Germany).gba"
build/gsmerge_de.gba build/tour_de`; likewise France/Italy/Spain with `gsmerge_fr/it/es`). The battle tour takes the encounter addresses from the profile.

The state files `build/tour/orig_field.ss` / `merged_field.ss` (Vale, start of the game) are created on demand
by `maptour.field_state`. Delete them after rebuilding the ROM.

### Ending / transition tests (ad-hoc scripts, see MODLOG session 6/7)

- "God mode" for tests: write Isaac's stats (0x02000500 +0x10/0x18/0x1A/0x1C base, +0x34/0x38/0x3C/0x3E/0x40
  current) to 9999 HP / 999 every few frames.
- Final battle + ending scenes: from a field state warp to map 187 entrance 2, press A repeatedly → ends in
  Faran's house (map 180, entrance 21).
- Credits: close menus, warp to map 0 entrance 9 → credits → (merged ROM) clear save + chapter card + TLA.
- Simulated end of credits: u16 0x02000402 = 2, warp to map 1.
- `tools/autoplay.py`: `screen_state()` classifies screenshots as dialogue / menu / field (window colour 0,99,132);
  `run_cutscene()` advances dialogue until idle.
- **Open gap:** the natural step Faran's house → Lalivero → Lemurian ship departure scene (map 188 entrance 99,
  event 0xF2) is not scripted; with an early-game test save, mid-game Lalivero events interfere.

Since the cartridge starts with the GS1 intro replay, every test that boots the merged ROM calls `Emu.to_menu()`
(START to skip the intro, wait for the menu to fade in) before pressing menu keys. Cached field states
(`merged_field.ss`) must be deleted after rebuilding.

Crash in the first frames: the bridge stops answering once mGBA halts on the crash; build a debug copy that
waits for a key before the suspect code (e.g. `while (!(~REG_KEYINPUT & 4)) {}`), set `bponce` breakpoints, press
the key. A test mGBA left over after a timeout keeps port 61337 busy: stop only the instance whose command line
contains `bridge.lua` (by PID).

## 3. Debugging workflow for relocation bugs

1. **Stray read** (merged ROM reads GS1's old area 0x08000000–0x087FFFFF while GS1 runs): the watch log gives pc,
   registers and the address. Run `tools/findptr.py "<GS1 rom>" <value>` to find where the unrelocated value is
   stored, then generalise a rule in `reloc.py` (avoid single-address hacks).
2. **Crash without stray reads** (bad data = a relocated word that was not a pointer): `bisect_reloc.py` reverts
   halves of the heuristic relocations to find the culprit; or compare RAM with `dumpmem`. Note: the GS1-only test
   ROM (`build_gs1_reloc.py`, empty lower half) can hide bugs that the merged ROM shows (zeros vs TLA data).
3. **Map-code patches**: disassemble with `thumbdis.dis(normalise_bls(code), 0x02008000, addr, n)` and check
   literal alignment (literals must be 4-byte aligned; `ldr rX,[pc,#imm]` base is `(pc+4) & ~3`).
4. **Playtest reports**: the player presses L + R + Select -> `build/reports/<time>.png/.ss/_vram|pal|oam|io.bin/_info.txt`
   and `<time>_recent_01..30.png` (one screenshot every 20 frames before the key press). Load the `.ss` in mGBA
   (bridge `load`) to inspect the moment.
5. **Playtest logger** (`PLAYTEST_EN.bat` / `PLAYTEST_DE.bat` → `tools/playtest_watch.lua`): writes `build/gsmerge_watch.log` and a
   savestate `gsmerge_watch_first.ss` if GS1 ever reads the old area while a human plays.

## 4. Tools that were tried and what they are for

- `compare_jumptables.py`, `fnmatcher.py`, `mapcode_calls.py`: function matching GS1 ↔ TLA (abandoned engine
  port, see TECHNICAL §8).
- `find_ptr_tables.py`: finds the MFT in an unknown ROM version (long pointer runs).
- `build_gs1_reloc.py` alone builds a GS1-only test ROM (lower 16 MiB empty).
