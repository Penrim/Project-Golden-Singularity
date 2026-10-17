# Golden Sun Merge – MODLOG

> Start here: docs/DEVELOPMENT.md (overview, setup, quick start), docs/TECHNICAL.md (reference), docs/TESTING.md (tests/debugging). This file is the chronological journal; newest entries at the bottom.

Goal: one GBA ROM hack containing Golden Sun 1 + The Lost Age as a single continuous game.
Route: ROM hack on top of The Lost Age (TLA); port GS1 content into it. Ship only a .bps patch.

## ROMs (never commit, never ship)
- Source zips: `Golden Sun ROM/` (user-supplied)
- Clean extracts: `work/goldensun/clean/` (work/ is gitignored)
- `Golden Sun (Germany).gba` – 8 MiB, code AGSD, SHA1 c23ab91a39434623cf1a999f387d743ade1a22a6
- `Golden Sun - Die Vergessene Epoche (Germany).gba` – 16 MiB, code AGFD, SHA1 7820b4c7ba9002b0e9be23a6f45a9ab204986438

## Recon (2026-10-12)
- No existing merged GS1+TLA hack found. Discussed in GS hacking Discord (Reddit, Jul 2024), nobody building it.
- No public GS decomp/disassembly found.
- Size is fine: 16 + 8 = 24 MiB, GBA max 32 MiB.
- Main tool: Atrius' Golden Sun: The Lost Age Editor v0.4 (2011), also reads GS1. Last working map editor:
  Teawater's unofficial "mapeditor" draft (goldensunhacking.net forum).
- Data lives in a Master File Table (MFT) of compressed files (formats 0/1 etc.).
- Map event logic = compiled ARM/Thumb "map code" files per map (TLA MFT index 1609+ per gs2randomiser wiki).
  -> Porting GS1 maps means porting compiled code whose calls target GS1 engine addresses; needs a
     GS1->TLA function address map. This is the hardest part of the project.
- All community docs/offsets target USA ROMs; our ROMs are German -> offsets differ.

## References
- GS Data wiki ROM map (GS1): https://gsdata.fandom.com/wiki/ROM_Map
- TLA map code list: https://www.gs2randomiser.com/doku.php?id=tla%3Amap_code
- Compression formats: http://forum.goldensunhacking.net/index.php?topic=2624.15
- Editor: https://www.romhacking.net/utilities/613/

## Findings session 1 (2026-10-12, German ROMs)
- MFT: GS1(AGSD) @0x31FE00, 975 files; TLA(AGFD) @0x680000, 1723 files. Entry0=ROM start, entry1=MFT itself.
- `tools/gsfs.py`: MFT reader + decompress fmt0/fmt1 (port of Karanum gs2-randomiser2, MIT). Works on both.
- Map code files: GS1 MFT 879..974 (96 maps), TLA MFT 1609..1722 (114 maps). Detect: decompressed starts `00 4c 20 47`.
  Header = 7 stubs `ldr r4,[pc]; bx r4; .word 0x0200xxxx` + `ldr r0,[pc]; bx lr; .word ptr`. Loaded at 0x02008000.
  Stored form keeps BLs in "absolute" encoding (see randomiser convertBranchLinks / `mapcode_calls.normalise_bls`).
- Map code calls the engine via literal-pool ROM pointers, mostly into JUMP TABLES at the start of engine code
  files (MFT 3,4,5,6,8,10,11; stub = `00 4c 20 47` + .word fn). File 0 (crt0, 0x080000xx) called directly.
  GS1 map code uses 386 distinct thumb fn pointers; 314 of 336 refs in the main engine files hit stub slots.
- Jump tables: GS1/TLA slot counts: f3 87/117, f4 134/135, f5 100/103, f6 192/303, f8 14/21, f10 1/6, f11 5/6.
  Slot order is NOT 1:1 (TLA inserted slots). Naive instruction-shape matching is noisy (tools/compare_jumptables.py).
  NEXT: proper function matching (disassembler-based: call graph + string/const refs, or REA/Ghidra), produce
  `gs1_to_tla_fnmap.json`. Then pointer-rewrite a GS1 map code file and load it in TLA.

## Architecture decision (pending user confirmation)
- Distribution can't be a plain patch vs TLA (would embed GS1 data) -> "bring your own ROMs" builder that reads the
  user's GS1 + TLA ROMs (+ optional other-language ROMs for language packs) and outputs the merged ROM.
- Multi-language: one engine base, text banks per language pulled from user's ROMs, language select at boot.
- User wants English (largest audience) + German, extendable to FR/IT/ES. Needs USA dumps for English.

## Session 2 (2026-10-12): US ROMs added -> US is the engine base
- `Golden Sun (USA, Europe).gba` AGSE, SHA1 5c4695205413df7db52b9a184815a07783999971, MFT @0x320000 (975 files)
- `Golden Sun - The Lost Age (USA, Europe).gba` AGFE, SHA1 b500663220cb9bf56b9f8e8c0c544f1d6fa3a824, MFT @0x680000 (1723)
- US vs DE (same MFT indices): GS1 differs in files 0-19 (engine code), 22, 28, 67-68, 94, 231, 425, 537, 686,
  746, 748-749, 772, 777, 800-801 and all map code 879-974. TLA differs in 0-17, 19, 22, 24, 27-31, 34, 128-164
  (scattered), 460, map code 1609-1722. Everything else is byte-identical after decompression.
  -> languages = swap text + a few graphics files on one engine. German needs its font (umlauts) too.
- Python venv `GoldenSunMerge/.venv` with capstone 5.0.7. Run tools with `.venv/Scripts/python -I`.
- `tools/fnmatcher.py` -> `data/fnmap_us.json`: disassembles every jump-table slot, normalises (GS1 returns
  `pop {rX}; bx rX` vs TLA `pop {pc}`; RAM literals -> EWRAM/IWRAM class), order-preserving DP alignment per file.
  Result: f3 69/87, f4 114/134, f5 83/100, f6 167/191, f8 13/14, f10 1/1, f11 4/5 matched.
- GS1 map code uses 278 distinct slot fns: 113 strong (>=0.8), 132 weak (0.35-0.8, need checking), 33 unmatched.
  Plus 107 non-slot thumb ptrs (file-0 crt0 helpers 0x080000C1.., and 0x080F9011 x86).
- Story flags: GS1 f5 slots 24/25/26 = flag get/set/clear (bit array in EWRAM, flag & 0xFFF).
  In TLA they are NOT in a jump table: get 0x081C1188, set 0x081C11AC, clear 0x081C11CC (mask 0x3FF, different
  base) -> TLA probably has a flag-range scheme; GS1 flags must be renumbered into a free TLA flag range.
- RAM layout differs: GS1 global ptr via `ldr =0x03001EBC`, TLA uses 0x0300006C (`movs #0xC0; lsls #0x12`).
  -> Porting map code also needs an EWRAM/IWRAM address map and struct-offset checks, not only fn pointers.

## Next steps
1. Global fallback search for unmatched slots (also search non-jump-table code, as with the flag fns).
2. Verify weak matches (call-graph consistency: matched callers should call matched callees).
3. Build RAM address map (literal-pool EWRAM/IWRAM refs of matched function pairs give pairs directly).
4. Understand TLA flag ranges; pick free range for GS1 flags.
5. Then: rewrite one GS1 map code file (Vale) + insert GS1 map data/tileset into a 32 MiB TLA, boot in mGBA.

## Session 3 (2026-10-12): PIVOT -> "two games, one cartridge" (dual engine)
Decision (made by Claude, user delegated "go ahead"): porting GS1 into the TLA engine is months of work.
Instead: one 32 MiB ROM, TLA unchanged at 0x08000000, GS1 relocated to 0x09000000, boot menu, later automatic
GS1 -> TLA transfer (replacing password/link). 100% content of both games works. Deeper merging can follow.

Tooling:
- mGBA 0.10.5 in tools/mgba (no --script); dev build 2026-10-08 in tools/mgba-dev (has --script + Lua
  setRangeWatchpoint). `tools/bridge.lua` (TCP 61337) + `tools/emu.py` drive it: keys/wait/read/write/shot/
  save/load/reset/regs, `watch lo hi` (first hit per frame, self re-arming), `watchall`/`unwatchall` (counting).
- Both US ROMs verified against mGBA's nointro.dat (flags verified).
- `tools/build_gs1_reloc.py` -> build/gs1_reloc.gba (test ROM: empty lower 16 MiB + GS1 at +16 MiB).
- `tools/difftest.py ORIG TEST OUT`: same inputs on both, screenshots + stray-read watch on 0x08000100-0x08FFFFFF.
  Screens differ only by timing (recompressed map code decompresses at a different speed) -> rely on the
  stray-read watch + visual checks.
- GOTCHA: don't name tool modules like stdlib (fnmatch.py, dis.py broke capstone imports). Renamed.

Relocation rules (tools/reloc.py, GS1 code region = 0x000000-0x320000):
- literal pools (Thumb ldr pc / ARM ldr pc), MFT, consecutive pointer runs >= 2 (code region only),
  strided struct arrays (stride 8..0x100, >= 3, code region only), singles = value equals a known target /
  odd ptr to a `push {..,lr}` / "near" (target within 64 KiB, code region, not inside disassembled code).
- Recursive-descent Thumb code coverage (`code_coverage`) guards the near rule.
- Data region (>= 0x320000): NO heuristics (they hit text/byte tables). Only MFT + m4a + map code.
- m4a music (tools/m4a.py): GS1 song table 0xFC684 (312 songs, starts before entries with 0 tracks).
  Track GOTO/PATT/REPT pointers are UNALIGNED (4282). Voicegroups incl. keysplit/drumkit recursion.
- Text (tools/gstext.py): GS1 text table 0x0736B8, 42 blocks; header {forest 0x08037464, offsets 0x08038334}
  at 0x03842C; text data 0x037464-0x0736B8 is PROTECTED (heuristics produced 33 false positives in length
  tables -> garbled menu text "Thect of Equipping"). Only header + table pointers relocated.
- Map code (MFT 879-974): decompress, relocate literal pools, then patch in place keeping token structure
  (compress.patch_c0/patch_c1; 11 files) or recompress fmt1 + append at 0x01800000+ (85 files; backrefs
  copied pointer bytes).
- Result: scripted run (intro, Vale, dialogue, menus) with ZERO stray reads, menus/text correct.

Known missed-pointer hunting loop: run, read `hits` (pc + regs), `tools/findptr.py ROM value` to find where the
unrelocated value is stored, then generalise a rule (never hand-patch single addresses unless unavoidable).

Next: merged ROM (TLA + GS1 + boot menu), flash save separation (both games use 64 KiB FLASH_V123),
then longer GS1 coverage tests (battle, world map, Psynergy, save/load).

## Session 3b: merged cartridge v0.1 WORKS (2026-10-12)
- `tools/build_merge.py GS1 TLA build/gsmerge.gba`: TLA at 0x08000000 (unchanged except flash patch + header
  branch), GS1 relocated at 0x09000000, boot menu at 0x09900000 (`tools/bootmenu.py`: two pre-rendered Mode 3
  images, keystone-assembled Thumb code; Up/Down + A).
- Saves: both games use AgbFlash FLASH_V123 (64 KiB). Cartridge now declares 128 KiB (Flash1M):
  - "FLASH_V123" marker -> "FLASH1M_V1" in both games.
  - chip table ids patched: Macronix 0x1CC2->0x09C2, Panasonic 0x1B32->0x1362 (Sanyo 1M) (TLA 0x17EEC/0x17F18,
    GS1 0x7B94/0x7BC0). Library then treats each 64 KiB bank as its whole chip.
  - boot code selects bank 1 once (mGBA only upgrades 512->1M when bank 1 is selected!), then GS1 -> bank 1,
    TLA -> bank 0. Verified: GS1 save in bank 1, TLA save in bank 0, neither touches the other, both reload.
- Boot: BIOS RegisterRamReset(0xFF) then jump (GS1 0x09000000 ARM, TLA 0x08000428 ARM).
- `tools/test_saves.py` = end-to-end save test. `PLAYTEST.bat` + `tools/playtest_watch.lua` = user playtest with
  stray-read logger (writes build/gsmerge_watch.log + gsmerge_watch_first.ss).
- GOTCHA: a leftover mGBA instance keeps port 61337 -> next bridge launch "doesn't come up". Kill by path filter.
- Watchpoint callback gets `info` table: address, width, oldValue, newValue, accessType, segment.

Next milestone: GS1 ending -> continue into TLA with GS1 party data (replace password/link transfer).

## Session 4 (2026-10-12): automated coverage instead of manual playtests
User asked for full automation instead of manual testing.
- GS1 map warp (CodeBreaker-derived): u16 map -> 0x02000400 (entrance at 0x02000402), u16 1 -> 0x02030170.
  Debug flag (TCRF): 0x03001F54 = 1 (US), 0x03001F64 (DE). Maps 191-198 empty, 199/200 debug rooms.
- `tools/maptour.py ORIG MERGED OUT`: warps to all 201 maps in both, walks, screenshots, stray-read log,
  crash-tolerant (restarts emulator). Result after fixes: 0 crashes, 0 stray reads; screen diffs = timing only.
- Encounter: GS1 0x0808AE74 = "check encounter" (step counter at 0x02000478, threshold, weighted group pick),
  returns enemy group in r0; wrappers return to 0x0808B03E / 0x0808B056. Bridge `forceret ADDR VAL` breakpoint
  sets r0 -> forces any battle while walking on world map (map 2).
- `tools/battletour.py`: forces every enemy group (1-255) in both ROMs, auto-fights with A, compares, logs.
- BUG FOUND by map tour: map 16 (Sol Sanctum room) crashed in merged ROM only (zeros in test ROM masked it):
  missed single pointer @0x2AC64C (0x082AC30C) in file 17 data. Root cause: code coverage seeded from a global
  BL scan of data marked data as code, which blocked the "near" rule. FIX: `strong_code_coverage` seeded only
  from trusted roots (jump-table stub targets, odd literal-pool/pointer-table targets with push prologue),
  iterating over literals of covered code. Coverage 366 KB.
- Watch ranges must start at 0x08000000 (not +0x100). `acclogf LO HI PATH` streams to a file (survives crashes),
  `dumpmem ADDR LEN PATH` dumps RAM in one frame. Test windows launch minimized (SW_SHOWMINNOACTIVE).
- GOTCHA: Write tool produces CRLF files; Python str.replace with "\n" patterns silently misses -> use Edit tool
  or handle \r\n. Also never write literal "\n" into Lua strings via Python heredoc.
- RESULT battle tour (groups 1-255, merged vs original): 0 crashes, 0 stray reads. 42 battle-start screens
  differ only by random formation size/composition (RNG timing), graphics/text correct.
- RESULT map tour after coverage fix: 201 maps, 0 crashes, 0 stray reads.

## Session 5 (2026-10-12): GS1 -> TLA transfer research (in progress)
TLA side:
- New game flow: name Felix -> "Transfer data from Golden Sun?" -> method (Link / Password) -> tier
  (Gold/Silver/Bronze) -> 64-char keyboard. Savestate: build/tour/tla_newgame.ss (at password entry, "AAAA").
- Password input buffer: 0x0200A74A (also copy at 0x02036E80), one byte per char = alphabet index 0..63,
  99 = empty. START jumps to "Finish"; invalid input -> "Invalid password."
- Decoder in TLA title map code (MFT 1610) at 0x0200A068(chars, nchars, out): nchars 16/61/260 -> out
  11/41/175 bytes. c[i] -= i (mod 64); every 10th char (i%10==9) is a row checksum and skipped; 6-bit values
  packed into bytes (shift scheme at 0x0200A0D6..); then all bytes XOR'ed with the last byte; CRC-like check after.
- Gold block = 175 bytes (levels, djinn, stats, items, coins, side-quest flags). Link transfer carries MORE
  (exact djinn order, equipment, settings) per wiki -> long-term: emulate link transfer.
GS1 side:
- Save = RAM image 0x02000000-0x02001FFF in two 4 KiB slots: slot n (0..2) = first half, n+3 = second half.
  Slot 3..5 header byte 7 = slot id. WriteSlot = 0x08005920(slot, src). Sector: "CAMELOT", id, u16 checksum,
  u16 counter, 0xFF0 data. Story flags at 0x02000040 (bit array, 0x200 bytes).
- "Save clear data" UI = 0x080207C4 (choose slot 0-2, then WriteSlot n and n+3) -> clear data uses the normal
  slots; "cleared" must be a marker in the saved RAM (not found yet; setting all flags did not unlock Send).
- Keys: held 0x03001AE8, newly pressed 0x03001C94 (VBlank handler 0x08003650).
- Title map code = MFT 880. Secret sequences table 0x020094D4: [SEL,SEL,SEL] and
  [U,D,U,D,L,R,L,R,U,R,D,L,U,SEL]; they raise menu option count (5 -> 4/7 loop). Wiki: hidden "Send" menu
  = hold R+Left and press B/Start on the title menu, requires clear data.
- GS1 password ENCODER not located yet (not in map code via mod-10 pattern; likely in engine/Send menu code).
OPEN: need a real cleared GS1 save (user?) or find the "cleared" marker; then capture GS1 encoder or decode
TLA's unpack of the 175-byte block.

## Session 6 (2026-10-12): chapter transition GS1 -> TLA WORKS (design approved by user)
Design (user approved): GS1 ending -> auto-save clear data (dedicated slot) -> "Chapter 2" card -> TLA new game
directly, no transfer questions, link-quality transfer; start menu with Continue / Chapter 1 / Chapter 2.
Key facts:
- GS1 "Send by cable" (title option 5) sends RAM 0x02000000..+0x1004 of a clear save. TLA cable receive
  (title map code 1610, fn 0x02008B24) receives into 0x02013000 and then (0x02008D0E) copies GS1 flags
  (+0x40, 0x214 bytes) and party data (+0x240, 0xD20 bytes) and processes chars 0-3 itself.
- Clear data = normal GS1 save with RAM byte 0x0200044F == 1. GS1 title map code 880: branch at 0x02008416
  (entered when u16 0x02000402 == 2, i.e. after the credits) asks "Save your adventure?" -> 0x080207C4.
  Test trigger: w16 0x02000402=2, warp to map 1.
- GS1 flash scan keeps slots 0..15 valid (older duplicates freed) -> dedicated clear slot 6 (+9) is safe.
- Camelot ABI: r4 is SCRATCH in game code (functions push from r5). C code calling game functions must be
  compiled with -ffixed-r4 (bug: second WriteSlot call jumped through clobbered r4).
- mGBA savestates do NOT restore the flash bank selection (always bank 0 after load) -> runtime selects banks
  explicitly.
- RAM 0x0203FFF0 survives TLA start-up -> mailbox "GMS2" = start new game directly.
Implementation:
- `cart/runtime.c` (Arm GNU Toolchain 14.2 in tools/armgcc, linked at 0x09B00000, no RAM sections):
  gs1_clear_available, gs1_clear_to_link_buffer, tla_receive_gs1, gs1_chapter_end (GS1 save fns at +16 MiB),
  tla_title_menu_override. Chapter card image at 0x09B10000.
- `tools/transfer_patch.py`: TLA 1610 patches (receive -> runtime; new-game hook before "Transfer data?"
  at 0x020084B6 -> Link path 0x020084EA if clear data; title hook at 0x020083F4 -> 0 = new game if mailbox),
  GS1 880 patch (0x02008416 -> gs1_chapter_end). Map-code BL "stored" encoding = target offset - 2.
- Verified end-to-end from power-on: GS1 -> card -> TLA naming Felix -> auto transfer -> Isaac's GS1
  equipment shown -> intro. Save: bank 1 slot 6/9 with marker.
TODO: start menu (Continue / Chapter 1 / Chapter 2) in C; verify real GS1 credits set 0x02000402=2.
- Start menu now in C (runtime.c boot_main): Continue (shown if any normal save; -> TLA if TLA save exists,
  else GS1) / Chapter 1 / Chapter 2. 5 pre-rendered screens at 0x09B30000; ARM stub at 0x09900000.
  Verified with tools/test_menu.py (empty cart, TLA save, GS1-only save).
- Regression map tour on final build: 0 crashes, 0 stray reads.
- build/DEMO_end_of_chapter1.ss = GS1 state right after the credits (for the user to watch the transition).
- Residual risk: real GS1 credits -> title with 0x02000402 == 2 not observed (inferred: it is the only clear-
  data save path).
- FIX (user report): after confirming Felix's name, TLA showed the received-party overview (looked like a
  bug). Source: TLA title map code 0x02008504 "bl 0x0200A3E8" (cable path review screen). Hook4 skips it
  when a GS1 clear save exists; hook3 at 0x02008574 skips the per-character naming loop (names come from GS1).
  The import itself (0x0200A370 -> 0x080AE410, args 0x02013000, 0=cable) still runs (verified with bplog).
  Now: confirm Felix -> story intro directly. Menu test re-verified.

## Session 7 (2026-10-12): real ending test
- GS1 final events: map 187 (Lighthouse Aerie). Entrance 1 = pre-battle scene, entrance 2 = "We did it" ->
  Fusion Dragon battle (map 510/347 = battle) -> scenes (187/3, 2/91, 187/93, 2/73, 187/4) -> Faran's house
  in Lalivero (map 180, entrance 99 -> 21) with control. Next: leave the house (down; NPC: "Please wait for me
  outside Faran's house") -> Lalivero map 178 entrance 7; further story steps needed before the credits
  (not scripted yet).
- Test helpers: god mode = Isaac struct 0x02000500 (+0x10 base maxHP, +0x18/1A/1C base atk/def/agi,
  +0x34 maxHP, +0x38 HP, +0x3C/3E/40 atk/def/agi). GS1 warp fn = 0x08091E3C(map, entrance) (sets
  [glob+0x170]=999, 0x02000400/402); event/door warps via 0x0808A6B4. `tools/autoplay.py` detects dialogue /
  menu from screenshots (window blue 0,99,132).
- RESULT: merged ROM runs the real final battle + ending scenes identically to the original (same map
  sequence), 0 stray reads, no crash.
- Static proof for the last step: the clear-data save routine 0x080207C4 is reachable ONLY via its stub
  (file 4 slot 93 @0x080152E9), referenced ONLY by GS1 title map code 880 at the "u16 0x02000402 == 2" branch
  (patched -> gs1_chapter_end). No BL callers, no other pointers. So the real credits must end there.
- CREDITS: map 0 entrance 9 = GS1 staff credits; afterwards title map 1 entrance 2 ("Save your adventure?")
  -> verified in original AND merged ROM: credits -> gs1_chapter_end -> clear save (bank 1 slot 6/9) ->
  Chapter 2 -> TLA naming. 0 GS1 stray reads.
- warp(0, 9) is called ONLY from map 188 (Lemurian ship, mapcode 970) fn 0x02008430 inside the departure
  cutscene 0x02008B34, registered in map 188's event table (entry 4 @0x020097AC, key 0xF204, cond 0xFFFF000A).
  Map 188 init arms event 0xF2 when entrance == 99 (0x0200A3A4(0, 0xF2)).
- GS1 exit tables (map code entry +0x14 getter): header = own map id, records (exit<<20)|(entrance<<12)|map,
  terminator 0x1FF. Lalivero (966) special entrances 90/91 set flags 0x9A7/0x9BF; flags 0x9B8/0x9BB/0x9BF
  are Lalivero mid-game events ("Please wait for me outside Faran's house" soldier).
- NOT achieved: the natural link Faran's house -> ship 188/99 -> departure cutscene. Our test state has early-
  game story flags, so mid-game events interfere; forcing 188/99 does not fire event 0xF2; calling the
  cutscene after init renders nothing (too early). Needs a realistic late-game flag set.
- Tools: bridge `acclogwf` (write log), `bplog`, `callafter FUNC TARGET`, `forceret`, `bpwrite`;
  tools/autoplay.py (screen_state incl. field menu, run_cutscene).

## Session 8 (2026-10-12): documentation
- Wrote README.md, docs/TECHNICAL.md, docs/TESTING.md. Removed scratch probe*.lua.
- User playtest log (build/old/gsmerge_watch.log) only contained TLA start-up reads right after the chapter
  transition (logger mode check runs once per frame) -> false alarm. playtest_watch.lua now switches to TLA mode
  when pc or lr is in 0x08000000-0x08FFFFFF. Verified: demo transition produces no log.

## Session 9 (2026-10-12): language support = one cartridge per language
- User choice (asked): one cartridge per language from the official ROMs (not a runtime switch).
  Reasons: both complete pairs = 48 MiB > 32 MiB; DE GS1 has 10908 strings vs US 10722 (TLA 12961 vs 12461)
  with different numbering (options strings missing/moved, items shifted), engine + map code use the language's
  own IDs; menus, umlaut keyboard and logos differ.
- `tools/gstext.py` now decodes text banks (Huffman forest per previous char, port of the randomiser):
  `load_bank(d, table, nblocks)`, `pretty()`. Cached banks: build/text_banks.pkl.
- `tools/profiles.py`: profile_gs1/profile_tla find every address by code patterns; `check_us()` asserts the
  hand-verified US values (passes). DE differences: GS1 save fns all shifted (+0x30 / -0x135C ...), song table
  0xFD484, encounter wrappers 0x0808E646/65E; TLA title map code shifted by -8 (receive fn 0x02008B1C, name loop
  0x0200856E, title fn 0x0200A2E8, review fn 0x0200A3E0). GS1 title map code layout identical in both.
- Build pipeline is profile-driven: build_merge.py --lang en|de -> build/gsmerge_<lang>.gba; runtime compiled per
  version pair with generated build/cart/<GS1>_<TLA>/profile.h; flash IDs found by find_flash_ids.
- Start menu / chapter card texts per language (bootmenu.TEXT); highlight box adapts to text width.
- EN rebuild identical to the previously verified ROM except the menu images.
- DE results: boot + GS1 intro in German, 0 stray reads; map tour 201 maps 0 crashes 0 stray reads (14 timing
  diffs). PLAYTEST_EN.bat / PLAYTEST_DE.bat replace PLAYTEST.bat.
- DE battle tour: groups 1-255, 0 crashes (merged and original), 0 stray reads; 11 battle starts differ >5%,
  checked by eye = random formations (same enemy, different count/position).
- test_saves.py was older than the 3-entry start menu (one DOWN = Chapter 1 once a save exists, so the "TLA"
  boots went to GS1). Now UP once = Chapter 2, UP twice = Chapter 1 (menu wraps; works with 2 or 3 entries).
  DE: GS1 -> bank 1 sectors [10, 13], TLA -> bank 0 [9, 10, 11], GS1 bank untouched, both reload (German file
  list "Jenna Venus-Leuchtturm").
- test_menu.py takes an optional GS1 bank file of the same language (DE: build/tour_de/gs1_backup.sav = bank 1
  of the save test). DE: same screens as EN (Fortsetzen -> TLA, GS1-only -> GS1).
- New tools/test_transition.py (automates the session 6/7 ad-hoc check + makes the demo state). DE: PASS,
  card "Kapitel 2 / Die vergessene Epoche", "Alex" (test name) in TLA RAM 0x02000520, clear data in bank 1 sectors [3, 12].
  Demo state build/gsmerge_de.ss1 (F1 in PLAYTEST_DE.bat).

## Session 10 (2026-10-12): start-menu title artwork
- User request: title screen art made with local ComfyUI, fitting Golden Sun's pixel look.
- ComfyUI portable (C:\ComfyUI\...), RTX 4070 Ti 12 GB. No pixel-art LoRA installed; used Z-Image Turbo
  (fp8 weights, qwen_3_4b encoder, 9 steps, ~8 s/image) via new tools/comfy_gen.py (HTTP API).
- Iterations: painterly prompt -> modern-looking lighthouse; "16-bit pixel art" prompt -> much closer to GBA
  look; layout had to be in the prompt (horizon at the middle, open sea in the lower half) because the menu
  entries otherwise cover the scene. Picked title_v4 seed 8 (sun behind a mountain island, elemental lighthouse,
  ship). Prompt + settings: art/README.md.
- tools/title_art.py: crop 3:2, box-downscale 1200x800 -> 240x160, 64-colour median cut without dither, 15-bit.
- bootmenu.render_art: gold-gradient "GOLDEN SUN" title, "Collection"/"Sammlung", entries with outline on a soft
  dark gradient (no box), highlight bar; the "Up/Down" hint line was dropped. menu_images uses art/title.png
  when present. Rebuilt EN + DE; checked in mGBA: menu, cursor, Chapter 1 -> GS1 boot.
- User did not like the pixel-art seascape; wants it closer to the original title screens, especially the logo.
- Reference: GS1 title = BG2 8bpp 256-colour picture (logo + sky baked together), map = tiles 0x100.. in reading
  order (VRAM 0x4000), BG0 + OBJ "PRESS START". TLA without a save goes straight to name entry (title not seen).
- Found the source: GS1 MFT file 22 (USA 0x3249E8, DE 0x3247E8) = palette 0x200 + graphics-LZ stream. The
  decompressor is ARM code at ROM 0x08001B70 (0x258 bytes, copied to RAM by 0x080053E8 and called via a bx-r6
  veneer). Format: flag byte MSB-first, 0 = literal, 1 = b1 b2 -> distance (b1>>4)<<8|b2, length (b1&15)+1,
  nibble 0 -> extra byte n, length n+17; distance 0 = end; flag byte 0 = 8 literals. tools/gfxlz.py matches VRAM
  exactly. tools/gbavideo.py renders BG/OBJ layers from VRAM/palette/OAM dumps (debug helper).
- tools/gs1_logo.py: title picture from the ROM, logo by colour (warm/dark vs. sky) + largest component; clean for
  USA and DE. The build reads it from the player's ROM (no original graphics in the repo; ROM-derived reference
  shots moved to build/art/ref).
- New sky (art/title_v6 seed 5, prompt in art/README.md): pastel airbrushed clouds, sun with rainbow halo,
  lighthouse + spire. bootmenu.render_classic: logo moved up 6 px, gold "Collection", game-style window (frame
  colours sampled from TLA's name-entry window), Verdana Bold 9 non-anti-aliased + shadow, yellow cursor.
  Rebuilt EN + DE; mGBA check: 2- and 3-entry menus, cursor, Fortsetzen -> GS1 (save present).
- User prefers TLA's logo (cleaner). TLA title (seen only with a save; with no save TLA goes straight to name
  entry; spamming A in the original TLA ends in the transfer password screen, so the TLA save was made in our
  cartridge via test_saves.py) = same layer setup as GS1, tiles from VRAM 0x6800. Source: TLA MFT file 22
  (0x684990 in USA and DE) = 224-colour palette (0x1C0) + Golden Sun format-0 stream (the title routine at TLA
  0x080128A8 is the format 0/1 dispatcher; the graphics LZ routine also exists at 0x165C). gsfs.decompress
  matches VRAM exactly.
- tools/gs1_logo.py -> tools/title_logo.py (gs1 + tla). TLA cut: warm/dark mask with looser thresholds (ring
  highlights), 8-connected shapes, keep largest + bronze ornament pieces, drop the subtitle band (olive letters
  x >= 64) and TM. Clean for USA and DE. Menu: LOGO_LAYOUT["tla"] (logo -6 px, "Collection" at (68, 87) size 12).
- emu.py now launches mGBA muted (-C mute=1 -C volume=0), user request.
- Rebuilt EN + DE, checked in mGBA (2/3 entries, cursor).

## Session 11 (2026-10-12): panning start screen
- User request: start screen = slowly panning panorama from GS1's title scene to TLA's, without logos; logo from
  TLA. Implemented:
  - TLA title picture decoded (see above); GS1/TLA pictures differ slightly between USA and DE (palette nuances,
    TLA subtitle, DE GS1 copyright line wider: first patch left a visible "(c)" -> copyright mask = full width,
    mask = union over languages, coverage() check = 0 for both).
  - ComfyUI inpainting (tools/comfy_gen.py inpaint_workflow + upload; LoadImage alpha = keep mask). First prompt
    named spire/lighthouse -> duplicates; filler-only prompt works. art/panorama_patch.png = generated pixels only.
  - runtime.c start menu rewritten: mode 0, BG2 8bpp ring of 32 tile columns streamed with CpuFastSet, logo as
    8 OBJ 64x64 8bpp, window on BG0 4bpp bank 15, fades. bootmenu.menu_data packs everything (header of offsets).
  - Checked in mGBA: pan GS1 -> TLA, no column glitches, cursor, boot. Tests: test_menu EN + DE, test_saves DE,
    test_transition EN + DE all pass (demo states regenerated). GIF: build/art/start_screen_pan.gif.
- Note: with a 2-entry window the GS1 spire and TLA lighthouse sit partly behind the window at the pan ends.
- User: the original screens must stay unchanged, only the middle generated. Title pictures have the logos baked
  in, so switched to the logo-free intro screens:
  - GS1 intro (frames ~300-570): BG1 4bpp clouds + BG2 8bpp spire (both 240x168 sequential tiles, from MFT file
    23 graphics LZ; the spire zoom is assembled per frame), sprites: sun (64x64) + 12 semi-transparent flare/ring
    pieces (BLDALPHA 14/14), WIN0 hides BG0. Frame 558 = last frame before the logo, matches the title framing.
    BG offsets are write-only -> found by brute-force matching (BG1 0/5, BG2 0/216). gbavideo.compose_frame
    reproduces the BGs pixel-exactly; flare/ring pixels differ from the screenshot only by one animation frame.
  - scene_recipe.py: recipe = per-32-byte-block references into decoded MFT files + maps as numbers; verified
    rebuilt-from-ROM == rebuilt-from-snapshot, EN recipe works unchanged on the DE ROM.
  - TLA intro valley: MFT file 25 (0x697D48 USA) = palette + graphics LZ, 240x384, logo-free; rows 128.. used.
  - Middle only inpainted (soft 24 px into originals during generation only); hard seams fixed by colour
    matching + 16 px build-time edge fade (a mirror fade made a visible spike at the TLA slope -> edge colour).
    Seed 7 chosen. Both ends now hidden partly by logo/window (sun, rings, lighthouse).

## Session 12 (2026-10-12): GS1 intro before the side pan
- User: start with GS1's original "pan up" (the intro), then smoothly into the side pan.
- bridge.lua: `record N PREFIX` (VRAM/pal/OAM/IO + screenshot every frame; one command per frame was too slow:
  each Python round trip costs >= 1 frame), acclogwf limit 2000 -> 50000.
- Recording 244-603: intro visible 290-568, flash at 569 (BLDCNT 0xBE, BLDY 16 written in frame 569 -> replay ends
  at 567). Palette fade-in 290-349 = lerp from (2,0,0), k/256, some recorded frames torn (k interpolated). All VRAM
  changes 290-567 come from MFT files 21/23 (+ maps as numbers); palette static after the fade.
- intro_timeline.py make/assemble/simulate; Python simulation == recording apart from flare timing; EN timeline
  works unchanged on the DE ROM. runtime.c intro_play executes the ops in vblank.
- Bug 1: stripping the window bits made the sun sprite (opaque, sky-coloured edges) blend additively -> bright
  square; windows now replayed (WIN0/1 H/V from the write log). Bug 2: WININ 0x3F3F for the whiteout enabled the
  garbage BG0 -> 0x3636. Bug 3: last frame contained the original white flash -> one white flicker.
- Transition: 8-frame fade to white -> menu fades in from white; pan eased (accelerate/brake), 1 s rest first.
- Tests need Emu.to_menu() (START skips the intro); test_menu EN+DE, test_saves EN, test_transition EN+DE pass.
  GIF: build/art/start_sequence.gif.
- Bug (user): after the switch to the side pan the upper half was wrong -> the intro leaves BG1/BG2 VOFS at 5/216;
  menu_setup only reset BG2HOFS. Now all 8 BG offset registers are zeroed. EN + DE rebuilt and checked.

## Session 13 (2026-10-12): music on the start screen
- User: no sound during the playtest. mGBA was not muted (portable config mute=0); the start sequence simply had
  no sound (SOUNDCNT/DMA1/TM0 all 0 until a game started).
- GS1's m4a functions found (profiles._m4a), intro song = 70 (bplog on m4aSongNumStart: song 19 at frame 25 =
  logo jingle, 70 at frame 281 = intro). DE seemed different (74 at 371) only because GS1 without a save skips
  the intro (74 = naming music); song numbering identical (checked by note data).
- First try crashed (white screen, CPU in undefined mode): SampleFreqSet divides via 0x080022EC -> IWRAM
  0x03000380, which GS1's start-up (0x0800300C) fills by DMA from 0x08000770 (0x1400 bytes); our boot skips that.
  Now copied in sound_start (no interrupts enabled). Debugging needed a key-wait debug build + new bridge `bponce`.
- Result: same sound register state as the original, player 1 plays song 70 (7 tracks) through intro and menu;
  intro still full speed (menu at frame 307). Tests: test_menu EN+DE, test_saves DE, test_transition EN+DE pass.

## Session 14 (2026-10-12): glitch report "above Isaac's sprite" (Vale prologue, Isaac's house)
- Scripted prologue on original vs merged, screenshots every 30 frames matched by content: all pixel-identical
  except timing (lamp-glow flicker, the cyan Psynergy rings / white flash, which the original shows too; user
  confirmed the rings are normal). Note: bridge runs are not frame-exact (the emulator keeps running between
  commands), so per-frame comparisons drift.
- Glitch not reproduced yet. User cannot easily take screenshots -> playtest_watch.lua: rolling screenshot every
  20 frames (build/reports/recent, 30 files) and report hotkey L + R + Select (screenshot, savestate, VRAM/pal/OAM/IO
  dumps, last ~10 s of screenshots, info). Tested with bridge.lua as a second --script.
- Located (user: "Dora and Isaac walk from the bed to the stairs, always above Isaac"): every frame recorded in both
  versions, frames matched by content -> ours 2291-2297/2333-2339 show a garbled sprite part above Isaac; OAM equal,
  OBJ tiles 0x104-0x119 differ. Sprite composition 0x0800AE..B0xx, IWRAM decompressor 0x030005E8/0x030007CC.
  Changed words read by the decompressor: 0x082BB454 (0x087E00F3, packed graphics) -> reverting it in a copy
  removes the glitch. Rule: strided (with two genuine near sprite pointers at stride 0x74/0x78/0x7C).
- Pointer probe (bridge ptrprobe, tools/pointer_probe.py): USA 116 data words wrongly relocated (byte tables
  08 07 06 04 / 08 08 08 08 and packed graphics) -> data/reloc_exclude_AGSE.txt, build honours it. Glitch scene
  clean. DE: 66 mapped by context first, then own probe run (see below).
- Gotchas: bridge path arguments must not contain spaces (watchwidth/ptrprobe list files -> %TEMP%); per-word
  watchpoints (1589) stall mGBA, one range watchpoint + Lua lookup is fast.
- DE probe: 117 data words (65 of the 66 mapped USA words confirmed) -> AGSD list = union (118).
- Regression after the exclusions: map tour + battle tour EN and DE: 0 stray reads, 0 crashes; differing screens
  = storm flashes / camera timing / random formations (checked). test_transition EN + DE: PASS.

## Session 15 (2026-10-13): release preparation (GitHub)
- Form: bring-your-own-ROM builder (a BPS/IPS patch against one game would have to contain the other game).
- Player entry build.py: SHA-1 check against the verified dumps (--force for others), .zip input, language from the
  game codes, prebuilt runtime, reference output SHA-1 (EN 3fde5ab3..., DE 9d87b87f...).
- Player needs only Python + Pillow 12.3.0 + capstone 5.0.9 (pinned): cart/prebuilt/<pair>/ (runtime.bin + meta.json
  with profile header and source hash; rebuilt automatically when the ARM GCC is present), data/asm_cache.json
  (tools/asmcache.py; keystone only for new snippets), art/ui/<lang>/ (menu texts pre-rendered; fonts only for
  python tools/bootmenu.py ui). Output byte-identical in all modes.
- Clean room (fresh venv, only requirements.txt, ROM zips, published files only): EN + DE identical to the reference.
- Legal/privacy: README (players), BUILDING.md, LEGAL.md, LICENSE (MIT, "Golden Sun Collection contributors"),
  THIRD_PARTY_NOTICES.md (Karanum gs2-randomiser2 MIT notice, Z-Image Turbo Apache-2.0, tools), CHANGELOG.md,
  issue template, .gitignore (ROMs/saves/states/zips), .gitattributes. Old README -> docs/DEVELOPMENT.md, MODLOG ->
  docs/. Test name changed to "Alex"; ComfyUI drafts with embedded workflow metadata moved to build/.
- Checks on the exported file set: no personal data/paths, no 32-byte piece of any of the four ROMs in any file,
  um publish check PASS (84 files).

## Session 16 (2026-10-14): French, Italian, Spanish
- ROMs (No-Intro): AGSF 42f3b262..., AGFF f14855c0..., AGSI ca45e04b..., AGFI 57f1d005..., AGSS de0bdc88...,
  AGFS a2e3e800.... GS1 MFT: FR/ES 0x321800, IT 0x320000 (longest pointer run starting with 0x08000000); TLA
  0x680000 everywhere. All profiles.py patterns matched unchanged (values in TECHNICAL "French, Italian, Spanish").
- Start screen sources identical in all five versions (panorama pixel-identical). TLA logo: the Italian subtitle is
  dark red, the old hue rule kept "L'" and two sky specks. New rule in title_logo.tla_logo: shapes right of the
  ornament = subtitle, shapes further left = subtitle if >= 90 % of their pixels have subtitle colours (letters
  >= 0.93, ornament <= 0.67), whitish specks dropped. German logo identical; English now keeps a small ornament
  curl the old rule had cut (EN output SHA-1 changes to 5a8c4f2a...).
- Menu texts FR/IT/ES (TEXT in bootmenu.py, official subtitles L'Âge Perdu / L'Era Perduta / La Edad Perdida).
- Parallel testing: GSMERGE_PORT (emu.py + bridge.lua), probe list file per ROM. test_transition reads the hero name
  at 0x02000500 (FR/ES default names differ: "Vlad", "Hans").
- Pointer probes (3 in parallel, ~27 min): 120/118/119 data words; + EN/DE findings mapped by 12 bytes of context
  (pointer_probe.py list ... OTHER_GS1.gba) -> AGSF 128, AGSI 127, AGSS 127.
- Tests FR/IT/ES: map tour 0 stray reads / 0 crashes; battle tour 0 crashes / 0 stray reads; saves, menu,
  transition PASS. Differing map screens = timing (checked; ES map 7 light effect and map 182 cutscene not
  reproducible / pixel-identical with equal timing). EN transition re-run PASS, DE output unchanged.
- Builder: SUPPORTED/PAIRS/NAMES for FR/IT/ES, reference SHA-1 FR 2de01797..., IT 569f1cbb..., ES d64dedca...;
  player build from roms/ zips byte-identical to the dev builds. VERSION 1.1.0 (not released, not committed).

## Hotfix 1.1.1 (2026-10-14): prebuilt runtime check
- Found while setting up a git worktree: cart/prebuilt/*/meta.json stored sha1(runtime.c + link.ld) of the author's
  working copy (runtime.c CRLF, link.ld LF). GitHub ZIP (LF) and git clone on Windows (CRLF) both mismatch, so
  build.py refused to use the precompiled runtime for every player without the ARM GCC (1.0.0 and 1.1.0). The
  earlier "clean room" test had used local files, not an export of the repository.
- Fix: fingerprint with LF line endings (transfer_patch.build_runtime), stored values updated (the old value was
  verified to be the same sources with CRLF runtime.c, so the runtime binaries are unchanged).
- Verified from `git archive` exports with CRLF and with LF line endings: all five languages build, output identical
  to the reference checksums. Release checks must use an export of the commit, never the working copy.

## Session 17 (2026-10-14/15): verification steps 3-5, release 1.2.0
- Map code: only jump-table entries are ROM addresses; three 16.16 coordinates in map code 881 were relocated by the
  old literal scan (0x08380000 = 2104.0) -> relocate_blob changes exactly the jump-table entries.
- typeflow: code/ROM spaces, literal-use tracking, cmp/cmn/tst fix (+75 dereferencing functions), DMA via stm,
  call veneers, IWRAM routine arguments.
- Step 5 by four parallel helpers (tables, singles, data, literals; branches step5-*, merged): no conflicting
  evidence; ~270 data words per version taken out of the relocation, one missed pointer added. Fixed: animation
  scripts, sprite frames, sprite +7 offsets, m4a velocities, 3 Thumb instructions in switch-table code, the fill
  pattern, halfword tables.
- Tests: CPU cap per emulator (tools/cpucap.py, once per process; nested caps multiply), at most 3 in parallel,
  regression scripts write to new folders (nothing deleted). Regression after the fixes: all green in five languages.

## Session 18 (2026-10-15): final accounting, last data words
- Final accounting per word (verify_all.py) with the tiling proof (tileproof.py), self-describing switch and function
  tables (reach.py) and dataproof for every program-area word: about 1 % of the ~31 300 pointer-like words per
  version are still open. mapexports.py (standalone): tables map code passes to the engine through its exports.
- A private cross-check showed 31-36 data words per version that the heuristics still relocated: menu font glyphs,
  the credits font, cursor bob offsets, sprite frames, three m4a track bytes, one item table field, particle byte
  tables, debug tiles. Each is now proven by the project's own evidence: new fontproof.py (the three UI tables,
  found and bounded by their reader code in all five versions) and dataproof sprite frames that share their tail
  with the next frame (USA table 0x30FBB4, entries 7/8). step5_apply: +34 EN, +35 DE, +31 FR, +33 IT, +35 ES
  exclusions; no other word changed (relocated count down by exactly these, every other changed word identical).
- All five cartridges rebuilt; no emulator regression run yet.
- Then the last two: fontproof also proves ROM blocks copied by a literal DMA setup into video memory (DE
  0x07A8E8: 64 bytes to OBJ palette RAM, DMA at 0x0801BEAA) and byte tables read by a counted ldrb loop (ES
  0x0FB778: 14-step loop at 0x080F9FDC). Neither rule claims any other pointer-like word in the five versions.
- step5_apply: a rerun labelled every listed word "probe + ..."; now "probe" stays only on words the pointer probe
  found, and a second run changes nothing.
- Regression (build/regress_0909, 3 emulators in parallel, CPU-capped, muted), all five languages: map tour 0 stray
  reads; battle tour 0 crashes / 0 stray reads (8-61 battle starts differ by random enemy count: same enemies,
  checked by screenshot; more than last time because the machine was busier and the bridge runs the game between
  commands); saves, menu, transition PASS.
- Test ports 61431+ no longer bound ("bridge did not come up"): WSL/Hyper-V had reserved 61358-61957; moved to
  61341-61345 (TESTING.md).
- Release 1.2.1 (about 50 values per language since 1.2.0, incl. the packed-image words of the "last 4 %" commit):
  Windows launcher with a fresh venv in three clean copies of the commit (git archive CRLF, git clone, archive
  with LF line endings), all ten ROMs in roms/: 15 of 15 cartridges identical to the reference checksums.

## Session 19 (2026-10-17): invisible chapter card
- Real playthrough: after the GS1 credits the "Chapter 2" card was a black screen for ~4 s. GS1's title screen
  leaves BG2's affine matrix/offset (0x04000020-2F) non-identity, and mode 3 draws BG2 through it (proven in mGBA:
  identity values make the card appear). It also leaves BLDCNT = 0x00FE (fade to black).
- Fix (runtime.c boot_tla_new_game): before mode 3, BG2PA/PD = 0x100, PB/PC/X/Y = 0, BLDCNT/BLDY/MOSAIC = 0.
  Runtime +80 bytes; prebuilt runtimes and asm_cache (new hook literals) regenerated, new reference SHA-1 in build.py
  (README/release notes keep the 1.2.1 values until the next release).
- test_transition.py missed it: the simulated end of the credits skips GS1's title screen. It now writes such
  leftovers (BG2 scaled x2 with origin off-screen, BLDCNT 0xFE, BLDY 16, mosaic) via `bpwrite` at gs1_chapter_end
  (bridge: several address/value pairs) and compares every card-phase screenshot (mode 3, every 20 frames) with the
  card image in the ROM. 1.2.1 builds EN/DE: FAIL (score 0.0); fixed builds: PASS (1.0).
- mGBA with a ROM in the temp scratchpad folder sometimes did not open the bridge; ROM copies in build/ work.
- Clean clones (git clone CRLF, LF checkout) + patch: build.py without ARM GCC, 10 of 10 cartridges identical to
  the new references.
- Regression (build/regress_card, 3 emulators in parallel, uncapped, muted), all five languages: map tour 0 stray
  reads; battle tour 0 crashes / 0 stray reads; saves, menu, transition PASS.
