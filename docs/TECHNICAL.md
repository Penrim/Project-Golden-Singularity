# Technical reference

All addresses are for the **USA ROMs** (GS1 = AGSE, TLA = AGFE) unless noted. The build does not use these
numbers directly: `tools/profiles.py` finds them in any language version (see §7). "Offset" = position in the ROM
file; "address" = GBA bus address (ROM file offset + 0x08000000). In the merged cartridge GS1 lives at
+0x01000000, so a GS1 address 0x08xxxxxx becomes 0x09xxxxxx.

---

## 1. Cartridge layout (`build/gsmerge_<lang>.gba`, 32 MiB)

| File offset | Bus address | Content | Built by |
|---|---|---|---|
| 0x0000000 | 0x08000000 | TLA (16 MiB), unchanged except: header word 0 = branch to boot stub; flash ID table; "FLASH1M_V1" marker; MFT entry 1610 → patched title map code | `build_merge.py` |
| 0x1000000 | 0x09000000 | GS1 (8 MiB), relocated; flash ID table + marker patched | `build_gs1_reloc.py` |
| 0x1800000 | 0x09800000 | recompressed GS1 map-code files (85 of 96), MFT entries point here; ends ~0x1878C74 | `build_gs1_reloc.py` |
| 0x1900000 | 0x09900000 | ARM boot stub: `ldr r0,[pc]; bx r0; .word boot_main|1` | `bootmenu.boot_stub` |
| 0x1A00000 | 0x09A00000 | TLA title map code (MFT 1610), patched + recompressed (format 1) | `transfer_patch.patch_tla_title` |
| 0x1B00000 | 0x09B00000 | C runtime (`cart/runtime.c`, linked by `cart/link.ld`) | `transfer_patch.build_runtime` |
| 0x1B10000 | 0x09B10000 | "Chapter 2" card, 240×160 BGR555 (76 800 bytes) | `bootmenu.render_chapter_card` |
| 0x1C00000 | 0x09C00000 | GS1 intro replay: header (op offset, base palette offset, frames, sources offset) + decoded ROM files + base palette + op stream, ~310 KB | `intro_timeline.assemble` |
| 0x1B30000 | 0x09B30000 | start-menu data: header (9 u32: columns, offsets of BG palette, panorama tiles, OBJ palette, logo tiles, window tiles; window state size, first row, rows) + data, ~190 KB | `bootmenu.menu_data` |

Boot: BIOS → 0x08000000 (ARM branch) → 0x09900000 stub → `boot_main` (Thumb, C).
Game entries: GS1 0x09000000 (ARM; its own header branch is PC-relative → 0x090003C0), TLA 0x08000428 (ARM).

---

## 2. Save memory (flash)

Both games use Nintendo's AgbFlash library v1.23 (FLASH_V123, 64 KiB). The cartridge declares 128 KiB
(Flash1M, two 64 KiB banks): **bank 0 = TLA, bank 1 = GS1**. Each game only ever sees its own bank.

- Marker string "FLASH_V123" → "FLASH1M_V1" in both games (same length) so emulators/flash carts pick 128 KiB.
- Chip ID table (struct of 0x2C bytes per chip, IDs at +0x28): Macronix 0x1CC2 → 0x09C2 (MX29L010),
  Panasonic 0x1B32 → 0x1362 (Sanyo LE26FV10N1TS). Offsets: TLA 0x17EEC / 0x17F18, GS1 0x7B94 / 0x7BC0. The
  library then drives a 128 KiB chip with the 64 KiB routines, i.e. inside the selected bank.
- Bank select (runtime `flash_bank`): AA→0x0E005555, 55→0x0E002AAA, B0→0x0E005555, bank→0x0E000000.
  **Bank 1 is always selected once first**: mGBA starts every game as a 64 KiB chip and only upgrades to 128 KiB
  when bank 1 is selected.
- mGBA savestates do **not** restore the selected bank (after loading a state it is bank 0). The runtime selects
  banks explicitly before every flash access it makes.

### Golden Sun save format (same family in TLA)

16 sectors of 4 KiB per bank. Sector: `+0 "CAMELOT"`, `+7 slot id`, `+8 u16 checksum`, `+0xA u16 counter`,
`+0x10` 0xFF0 bytes of data. A GS1 save is the RAM image 0x02000000..0x02001FEF in two slots: slot *n*
(0..2) = 0x02000000+, slot *n+3* = 0x02001000+. Slot 3..5 are those second halves. On start-up GS1 scans all
sectors; any valid sector with slot id 0..15 is kept, older duplicates of the same slot are freed.

- GS1 WriteSlot = 0x08005920(slot, src); flash scan 0x080056CC; sector table in RAM at *(0x03001F1C).
- **Clear data** (finished game) = a normal save whose RAM byte **0x0200044F == 1**. The merged cart writes
  it to a **dedicated slot 6 (+9)** so normal saves are never overwritten.

---

## 3. GS1 relocation (`tools/reloc.py`, `build_gs1_reloc.py`)

GS1 is copied to +16 MiB and every absolute ROM pointer (0x08000000..0x087FFFFF) gets +0x01000000.
Sources of pointers and the rules that find them (all in the code region 0x000000–0x320000 unless noted):

| Source | Rule |
|---|---|
| Literal pools | words loaded by Thumb `ldr rX,[pc,#imm]` or ARM `ldr rX,[pc,#±imm]` |
| Master File Table | GS1 MFT at 0x320000 (975 entries) |
| Pointer runs | ≥ 2 consecutive pointer-like words |
| Struct arrays | pointer-like words at a constant stride 8..0x100, ≥ 3 in a row |
| Singles | value equals a known target (BL target / already-relocated value), or odd value pointing at a `push {…,lr}`, or "near" (target within 64 KiB of the word) **and** the word is not inside disassembled code |
| Music (m4a) | `m4a.py`: song table (starts 0xFC684, 312 songs; entries with 0 tracks exist), voicegroups incl. keysplit/drumkit recursion, and **unaligned** GOTO/PATT/REPT pointers inside track streams (4 282) |
| Text | `gstext.py`: block table 0x0736B8 (42 blocks of 256 strings, entry = {bitstream ptr, lengths ptr}), header {forest 0x08037464, offsets 0x08038334} at 0x03842C. The text data 0x037464–0x0736B8 is **protected**: no heuristic may touch it |
| Map code | see below |

- **Data region (≥ 0x320000): no heuristics** — they hit compressed data and byte tables (that produced
  garbled text "Thect of Equipping" once). Only MFT, music and map code are relocated there.
- **Code coverage** (`strong_code_coverage`): recursive-descent Thumb disassembly started only from trusted roots
  (engine jump-table stub targets, odd literal-pool / pointer-table targets with a `push` prologue), iterated over
  the literals of covered code. A global BL scan must **not** be used as roots: data that looks like BL
  instructions turned data into "code" and blocked the near rule (crash on map 16, Sol Sanctum).
- Engine jump tables: MFT code files start with stubs `00 4c 20 47` = `ldr r4,[pc,#0]; bx r4; .word fn`.

### Map code

Every map has a compressed "map code" file (GS1 MFT 879–974, TLA 1609–1722) that is decompressed to
**0x02008000** and run there. Header: 6–7 stubs (`ldr r4,[pc]; bx r4; .word fn`), the getter at +0x14
returns the map's exit table. Map table: GS1 0x09F1A8, TLA 0x0F17A8, 8-byte entries {u16 map-code file, u16
area/type, u16 id, u16 ?}.

- In the stored form, BL instructions are kept in an "absolute" encoding: stored offset field = target offset in
  the map code − 2 (`mapcode_calls.normalise_bls` converts to normal; `transfer_patch.to_stored_bl` converts back).
- Relocation of map code: decompress, relocate literal-pool pointers, then
  `compress.patch_c0/patch_c1` re-encodes **with the same token structure** if possible (11 files: identical size
  and timing, patched in place), else recompress with format 1 and append at 0x09800000+ (85 files).
- Compression: format 0 (bit-level, LSB-first, literal = 1 flag bit + 8 bits) and format 1 (LZ, flag byte, 12-bit
  offset, 4-bit length, long form). Ported from Karanum/gs2-randomiser2 (MIT).

### Camelot calling convention (important!)

Golden Sun's compiler treats **r4 as a scratch register** (functions push from r5). C code that calls game
functions must be compiled with **`-ffixed-r4`**; otherwise GCC keeps values in r4 across calls and the game
destroys them (this crashed the second WriteSlot call once).

---

## 4. C runtime (`cart/runtime.c`)

Built with `arm-none-eabi-gcc -mcpu=arm7tdmi -mthumb -Os -ffreestanding -nostdlib -fno-builtin -ffixed-r4`,
linked at 0x09B00000, **no .data/.bss** (asserted in `link.ld`). ARM7TDMI = Thumb-1 only: all hand-written hook
code is checked for Thumb-2 encodings (`transfer_patch._asm`).

| Function | Called from | Does |
|---|---|---|
| `boot_main` | boot stub at power-on | start menu: detects normal saves in both banks, Continue (TLA save → TLA, else GS1) / Chapter 1 / Chapter 2; panning panorama (below); fade out, selects bank, BIOS RegisterRamReset(0xFF), jumps to the game |
| `gs1_clear_available` | TLA hooks | 1 if bank 1 holds GS1 clear data (slot 6, else slots 0–2 with marker) |
| `gs1_clear_to_link_buffer` / `tla_receive_gs1` | TLA patched cable receive | copies exactly what GS1's "Send (cable)" transmits: RAM image 0x02000000..+0x1004 of the clear save, into TLA's receive buffer 0x02013000 |
| `gs1_chapter_end` | GS1 title map code ("after the credits" branch) | sets clear marker, saves via GS1's own routines into slot 6/9, shows the chapter card (~4 s or A/Start), resets RAM, writes mailbox, jumps to TLA |
| `tla_title_menu_override` | TLA title hook | consumes the mailbox → "New Game" |

Mailbox: u32 at **0x0203FFF0** = 0x32534D47 ("GMS2") means "start TLA's new game directly". This address
survives TLA's start-up until its title code runs (tested).

GS1 functions are called at their relocated addresses (`GS1_FN(a) = a + 0x01000000 + 1`): 0x080056CC flash scan,
0x08005C68, 0x0801F818 (prepare save data), 0x0808A5B0 (actor positions), 0x08005920 WriteSlot. This mirrors
GS1's own clear-save routine 0x080207C4 without its menus.

---

## 5. Patches in the games' title code

### TLA title map code (MFT 1610, runs at 0x02008000) — `transfer_patch.patch_tla_title`

Free space for hooks: the body of the original cable-receive function (0x02008B30..0x02008D0D) is no longer used.

| Site | Original | Patch |
|---|---|---|
| 0x02008B30 (receive fn 0x02008B24 after its prologue) | cable receive loop | call `tla_receive_gs1`; success → original "process received data" path 0x02008D0E (copies GS1 flags +0x40/0x214 bytes and party +0x240/0xD20 bytes, recalculates the 4 characters), failure → epilogue 0x02008D6E (r0 = -1) |
| 0x020084B6 | "Transfer data from Golden Sun?" (`ldr r0,=0x24; movs r1,#13`) | `bl hook1` (0x02008B48): if clear data exists → r5 = 1, r8 = -1, jump to the Link path 0x020084EA; else run the question as before |
| 0x020083F4 | `bl 0x0200A2F0` (title screen; result 0 leads to New Game) | `bl hook2` (0x02008B74): if mailbox set → return 0 (New Game), else original |
| 0x02008574 | `movs r6,#0; movs r7,#1` + per-character overview/naming loop | `bl hook3` (0x02008B98): if clear data → skip to 0x020085A8 (names come from GS1) |
| 0x02008504 | `bl 0x0200A3E8` (overview of the received party) | `bl hook4` (0x02008BC4): if clear data → skip, else original (r0–r3 preserved) |

The real import (0x0200A370 → 0x080AE410, args 0x02013000, 0 = cable) still runs after the hooks.

### GS1 title map code (MFT 880) — `transfer_patch.patch_gs1_title`

0x02008416 (branch taken when u16 0x02000402 == 2, i.e. after the credits: "Save your adventure?") →
`ldr r3,=gs1_chapter_end; bx r3`. The clear-data save routine 0x080207C4 is reachable **only** through this
branch (its only reference is the file-4 jump-table stub 0x080152E9, used only by map code 880).

---

## 6. Game facts reference

### GS1 (AGSE)

| What | Where |
|---|---|
| MFT | 0x320000, 975 entries; map code files 879–974 |
| Map table | 0x09F1A8 (201 maps) |
| Current map / entrance | u16 0x02000400 / u16 0x02000402 |
| Warp | 0x08091E3C(map, entrance): [*(0x03001EBC)+0x170] = 999, writes 0x02000400/402. Debug/test warp: write map + entrance, then u16 1 → 0x02030170 |
| Exit tables | map code getter at +0x14; header = own map id, records `(exit<<20)\|(entrance<<12)\|map`, end 0x1FF; processed by 0x0808A5F8 |
| Story flags | bit array at 0x02000040 (0x200 bytes); get = file 5 slot 24 (0x08079338 / stub 0x080770C1), set/clear slots 25/26 |
| Keys | held 0x03001AE8, newly pressed 0x03001C94 (VBlank handler 0x08003650) |
| Encounter | 0x0808AE74 returns enemy group (step counter 0x02000478); wrappers return to 0x0808B03E / 0x0808B056 |
| Character struct | Isaac 0x02000500, stride 0x14C: +0x00 name, +0x0F level, +0x10 base max HP, +0x12 base max PP, +0x18/1A/1C base atk/def/agi, +0x34 max HP, +0x36 max PP, +0x38 HP, +0x3A PP, +0x3C/3E/40 atk/def/agi |
| Song table | 0x0FC684 (m4a) |
| Text | block table 0x0736B8 (see §3) |
| Title map code | MFT 880; secret title sequences table 0x020094D4; hidden Send menu: R+Left+B on the title menu (needs clear data) |
| Final events | map 187 (Lighthouse Aerie): entrance 1 = pre-battle, 2 = "We did it" → Fusion Dragon battle → scenes → Faran's house (map 180, entr. 99 → 21) → Lalivero (178). Map 188 (Lemurian ship) departure cutscene 0x02008B34 (event 0xF2, armed for entrance 99) calls warp(0, 9) = **credits**; credits end → map 1 entrance 2 |
| Debug mode | 0x03001F54 = 1 (German: 0x03001F64) |

### TLA (AGFE)

| What | Where |
|---|---|
| MFT | 0x680000, 1723 entries; map code 1609–1722 |
| Map table | 0x0F17A8 (325 maps) |
| Title map code | MFT 1610: password entry 0x02008E44, decoder 0x0200A068 (16/61/260 chars → 11/41/175 bytes), password buffer 0x0200A74A (char index 0..63, 99 = empty), cable receive 0x02008B24 |
| GS1 import | 0x080AE410 (via 0x0200A370) |
| Character struct | Isaac's slot at 0x02000520 (+0x20 vs GS1), stride 0x14C |
| Text | forest 0x5F914, offsets 0x60A4C, block table 0xA9F54 (from the TLA randomiser) |

### German vs US

Same MFT layout. Byte-identical except: GS1 files 0–19, 22, 28, 67–68, 94, 231, 425, 537, 686, 746, 748–749,
772, 777, 800–801 and all map code; TLA files 0–17, 19, 22, 24, 27–31, 34, 128–164 (scattered), 460 and all map
code. German MFT: GS1 at 0x31FE00, TLA at 0x680000.

### French, Italian, Spanish

Same MFT layout and the same patterns as US/German (2026-10-14). GS1 MFT: France and Spain at 0x321800, Italy at
0x320000; TLA at 0x680000 in all versions. All `profiles.py` patterns match unchanged; values that differ from US:

| Key | France (AGSF/AGFF) | Italy (AGSI/AGFI) | Spain (AGSS/AGFS) |
|---|---|---|---|
| GS1 `text_table` | 0x073914 | 0x072B20 | 0x073210 |
| GS1 `song_table` | 0x0FEE84 | 0x0FC684 | 0x0FEE84 |
| GS1 `fn_flash_scan` / `fn_write_slot` | 0x080056DC / 0x08005930 | 0x0800570C / 0x08005960 | 0x0800572C / 0x08005980 |
| GS1 m4a `init` / `vsync` / `main` / `song_start` | 0x080FCAA0 / 0x080FC444 / 0x080FCB18 / 0x080FCB24 | same as US | same as France |
| TLA `recv_success` / `review_fn` / `title_fn` | 0x02008D06 / 0x0200A3E0 / 0x0200A2E8 (= German) | = German | 0x02008D02 / 0x0200A3DC / 0x0200A2E4 |

The start screen sources are the same files in all five versions (GS1 files 21/23 and the used parts of file 3,
TLA valley picture): the panorama is pixel-identical. The TLA logo differs only in the subtitle; `title_logo.py`
removes it by position (shapes right of the ring's ornament) plus colour (shapes further left whose pixels are
>= 90 % subtitle colours; the ornament shares at most 67 %). The Italian subtitle is dark red, so the earlier
hue-only rule missed it.

---

## 7. Language versions and profiles (`tools/profiles.py`)

One cartridge per language, built from that language's official GS1 + TLA ROMs (decision of 2026-10-12).
`profile_gs1(path)` / `profile_tla(path)` locate every address the build needs by instruction patterns; the
patches and the C runtime (`build/cart/<GS1code>_<TLAcode>/profile.h`) are generated from them.

| Key | Found by | USA | Germany |
|---|---|---|---|
| GS1 `mft_off` / `code_end` | MFT search | 0x320000 | 0x31FE00 |
| GS1 `text_table` | length-sum check | 0x0736B8 (42 blocks) | 0x07A618 (43 blocks) |
| GS1 `song_table` | best run of m4a headers, walked back | 0x0FC684 | 0x0FD484 |
| GS1 `cleared_branch` | `ldr r3,=0x02000240; movs r0,#0xE1; … cmp r3,#2; bne` in title map code | 0x02008416 | 0x02008416 |
| GS1 `clear_marker`, `slot_var` | literals in that branch / the save routine | 0x44F, 0x02002004 | same |
| GS1 save routines (`fn_flash_scan`, `fn_save_init`, `fn_prepare`, `fn_actors`, `fn_write_slot`) | call order inside the clear-data save routine (`bl P; bl A; ldr r5,=0x02000000; …; bl WriteSlot`) | 0x080056CC, 0x08005C68, 0x0801F818, 0x0808A5B0, 0x08005920 | 0x080056FC, 0x08005C98, 0x0801E4BC, 0x0808DBB0, 0x08005950 |
| GS1 `encounter_returns` (tests) | the two wrappers around "check encounter" in engine file 6 | 0x0808B03E, 0x0808B056 | 0x0808E646, 0x0808E65E |
| TLA `entry` | header branch | 0x08000428 | 0x08000428 |
| TLA `recv_fn` | only function loading 0x04000128 (SIOCNT) in title map code | 0x02008B24 | 0x02008B1C |
| TLA `recv_success`, `recv_epilogue`, `recv_buffer` | `ldr r5,=0x02000040 … ldr r1,=0x02013040`; `add sp,#4; pop {r3,r5,r6}` | 0x02008D0E, 0x02008D6E, 0x02013000 | 0x02008D06, 0x02008D66, 0x02013000 |
| TLA `link_path`, `review_call/fn` | new-game call of the receive fn followed by `adds r7,r0,#0; cmp r7,r8; beq; bl REVIEW` | 0x020084EA, 0x02008504 / 0x0200A3E8 | 0x020084EA, 0x02008504 / 0x0200A3E0 |
| TLA `ask_transfer` (+`ask_msg`) | `ldr r0,=MSG; movs r1,#13; bl; movs r0,#1; movs r1..r3,#0; bl` | 0x020084B6 (0x24) | 0x020084B6 (0x24) |
| TLA `title_call/fn` | `bl F; adds r5,r0,#0; cmp r5,#0; bge` | 0x020083F4 / 0x0200A2F0 | 0x020083F4 / 0x0200A2E8 |
| TLA `name_loop` (+body/done) | `movs r6,#0; movs r7,#1; movs r0,#6; bl; adds r0,r6,#0; bl` … `adds r6,#1; cmp r6,r7; blt` | 0x02008574 | 0x0200856E |
| Flash ID offsets (`find_flash_ids`) | struct with totalSize 0x10000 near "FLASH_V" | GS1 0x7B94/0x7BC0, TLA 0x17EEC/0x17F18 | GS1 0x7BC4/0x7BF0, TLA 0x17F18/0x17F44 |

Hooks in TLA's title code are placed at fixed offsets after `recv_patch_at`; the build asserts that this address is
4-byte aligned (the hooks' literal pools depend on it) and that all hooks end before `recv_success`.

Why not one cartridge with a language switch: German GS1 has 10 908 strings vs 10 722 (TLA 12 961 vs 12 461)
with different numbering (e.g. the options strings are elsewhere), and engine + map code reference the
language's own numbers; menus, the name-entry keyboard and logos differ too. Both complete language pairs would
need 48 MiB. A text decoder for the banks is in `gstext.py` (`load_bank`, `pretty`).

## 8. Abandoned approach (for context)

The first plan was to port GS1's content into TLA's engine. `fnmatcher.py` matches GS1 engine functions to TLA
ones (`data/fnmap_us.json`: 451/532 jump-table functions; GS1 map code uses 278 of them). It was dropped because
map code, RAM layout, flags, text, sprites and battles would all need translating; the dual-engine cartridge
gives the same player experience with 100 % of both games working.

## Start screen (panning panorama)

- Picture sources, all read from the player's ROMs at build time:
  - GS1 end: the last intro frame before the logo, rebuilt with `scene_recipe.render_recipe` from
    `art/gs1_intro_recipe.json` (VRAM/palette block references into MFT files 23 etc.; tile maps as numbers; OAM,
    IO, scroll) and `gbavideo.compose_frame` (BG priorities, WIN0 layer mask, sprites, semi-transparent alpha).
  - TLA end: intro valley picture (MFT file with 0x200 palette + graphics LZ, 240x384), rows 128..287.
  - TLA logo (`title_logo.py`): title picture (file 22, 0x1C0 palette + format 0) minus subtitle/TM.
  - Middle: `art/panorama_patch.png` (generated, colour-matched); `panorama.compose` adds a 16 px fade towards the
    originals' edge colours inside the middle.
- Hardware (`runtime.c boot_main`): mode 0, DISPCNT 0x1540.
  - BG2 0x1482: 8bpp, chars at VRAM 0, map 0xA000 (256x256). Map entry (row r, col c) = tile c*20+r, so map
    column c always shows ring slot c; panorama column X (8 px, 20 tiles = 1280 bytes, column-major in ROM) is
    copied into slot X % 32 (BIOS CpuFastSet in vblank). Columns lo..lo+31 are loaded; scrolling only writes
    BG2HOFS. BG palette 1..239 = panorama (quantised with dithering), 240..255 = window.
  - OBJ: logo + gold "Collection" as 8 sprites 64x64 8bpp (4x2, exactly the 32 KB OBJ VRAM), OBJ palette 1..255.
  - BG0 0x150C: 4bpp, chars 0xC000, map 0xA800, palette bank 15; tile rows 13..19 = window (210 tiles); the 5
    window states (Continue x3, without x2) are 6720 bytes each and replaced on cursor moves.
  - Pan: 1 px per 3 frames over 480 px (24 s), rest 150 frames at each end, ping-pong. Fade in/out via BLDY.
- Power-on sequence (`boot_main`): `intro_play` replays GS1's intro (frames 290-567 of the original: fade-in from
  (2,0,0), camera gliding up Mt. Aleph, sun and lens flares) -> 8-frame fade to white (WININ 0x3636 so the
  brightness effect works inside the game's windows) -> forced blank while `menu_setup` loads -> the panorama
  (starting on the same view) + logo + window fade in from white -> 1 s rest -> eased side pan. A/START skips.
- Intro op stream (`intro_timeline.py`, 12-byte ops): COPY (CpuFastSet from the decoded-file area of the blob to
  VRAM/OAM), DATA (inline tile-map / OAM bytes), REG (16-bit IO write: scroll, windows, blending, DISPCNT/BGCNT),
  FADE (palette = (2,0,0) + (base - (2,0,0)) * k >> 8, k fitted per recorded frame), FRAME, END. Made from an mGBA
  recording (`bridge.lua record N PREFIX` = full dump + screenshot every frame; `acclogwf` on 0x04000010-5F for
  the write-only registers; dump N uses the register writes of frame N+1). The windows must be replayed: the sun
  sprite is opaque with sky-coloured edges and the windows switch off blending for it.
- Pan easing: speed in 1/256 px/frame, +1 per frame up to 85, braking when v^2/2 >= remaining distance.
- Music: the start sequence plays GS1's own intro/title music (song 70, same number in USA/DE) with GS1's
  MusicPlayer2000 engine, without interrupts: `sound_start` copies GS1's IWRAM code (DMA image at 0x08000770,
  0x1400 bytes, normally copied by GS1's start-up; it holds the division helpers SampleFreqSet calls via
  0x03000380), calls m4aSoundInit and m4aSongNumStart(70) 9 frames before the first intro frame (as in GS1);
  every frame `frame_start` = wait for vblank + m4aSoundVSync (restarts the sound DMA), and m4aSoundMain (mixing)
  after the frame's work. `boot_game` stops DMA1/2, timer 0 and the sound master before RegisterRamReset.
  Addresses come from `profiles._m4a` (song-table literal -> m4aSongNumStart, wrapper before it = m4aSoundMain,
  push {r4-r6,lr} before that = m4aSoundInit, VSync by body pattern) and `profiles._iwram_image` (crt0 -> main ->
  2nd call -> first DMA3). USA: init 0x080FA2A0, main 0x080FA318, vsync 0x080F9C44, song start 0x080FA324.
  Without the IWRAM copy the engine runs into zeroed IWRAM and crashes (undefined instruction at 0x03007004).

## Relocation false positives and the pointer probe

The heuristics in `reloc.py` (pointer runs, strided struct arrays, near singles) also hit data that merely looks
like a pointer: byte tables such as 08 07 06 04 or 08 08 08 08 (stats/growth-like values) and packed sprite
graphics. Relocating them changes one byte (0x08 -> 0x09). Visible case: Vale prologue, Dora and Isaac walking from
the bed to the stairs, a garbled frame above Isaac (packed sprite word 0x082BB454 = 0x087E00F3, caught by the
strided rule together with two genuine internal sprite pointers at the same spacing).
`tools/pointer_probe.py` measures instead of guessing: one read watchpoint over GS1 (bridge `ptrprobe`/`ptrdump`)
records per candidate word narrow (8/16-bit) reads, 32-bit reads and "used" (the next reads hit the address it
holds). A word read byte/halfword-wise and not used is data -> `data/reloc_exclude_<code>.txt`, honoured by
`build_gs1_reloc.load_exclusions`. Music pointers are never excluded (m4a reads its pointers byte-wise).
USA probe (prologue + 201 maps + 255 battles): 3199 candidate words read; confirmed pointers 2005 (runs) / 158
(strided) / 33 (singles); byte-read data 116 after removing music pointers. Words never read keep the heuristic
result. Other versions: German 118, French 128, Italian 127, Spanish 127 (own probe run + the findings of the
versions done before, mapped by 12 bytes of surrounding context: `pointer_probe.py list ORIG OUT OTHER_GS1...`).
Byte-pattern rules were rejected: "all low bytes small" would also drop real function pointers (0x08011D11).

## Word accounting and code-use analysis (branch `pointer-analysis`, 2026-10-14)

Goal: replace "the heuristics probably got it right" by a counted list. Only words whose value lies in GS1's
address range (0x08000000 + size) can need relocation (USA: 27 031).

- `tools/wordmap.py GS1.gba [probe.txt] [--list CATEGORY]` gives every such word one category with its evidence:
  format-proven (mft, music, text-ptr), literal (loaded by confirmed code), typed-pointer / typed-data (code use,
  below), probe-pointer / probe-data, not-an-address (code, text-data, music-data, mapcode-file, file/data noise),
  guesses graded by table structure (guess-table: >= 4 pointer-like words in a row pointing nearby; guess-plausible;
  guess-WEAK-bytelike; guess-WEAK-isolated) and SUSPECT-* contradictions.
- `reloc.strict_code`: code coverage that does not wander into data. Odd literals only count as functions when
  they are BL targets of confirmed code or start with push {..., lr} (0x080F11BD is a byte table after the credits
  text); function pointers from tables only when their code does not run over table words (odd pointers into
  packed sprite data hit a 0xB5 byte about once in 256).
- `tools/typeflow.py`: abstract interpretation of every confirmed Thumb instruction with a control-flow graph
  (states merged at join points), value identities for index arithmetic ((i << 3) - i = 7i), engine stubs and
  `_call_via_rN` veneers resolved, per-function summaries "argument k is dereferenced" (fixpoint). A 32-bit load
  from a ROM table that is then used as an address (load/store base, BIOS decompress/copy source, DMA source,
  jump, dereferenced argument) proves the field a pointer; 8/16-bit reads prove data. Fields spread over the
  table up to the next label (an address code loads as a constant) and never over code. USA: ~1 800 words proven
  pointers, 12 data.
- Bugs found and fixed in the build (`build_gs1_reloc.classify`), the same in all five languages:
  - 4-5 Thumb instructions per version were relocated as a "pointer run" (two adjacent instructions forming
    0x08xxxxxx): lsrs rX,rX,#1 became lsrs #5 (USA 0x0FC6C, 0x0FC70, 0x94C34, 0xA1A4C, 0xA1A80). Guessed words on
    confirmed instructions are now dropped, except words that confirmed code loads PC-relative (switch tables).
  - 6 data words per version in halfword tables (code reads them with ldrh): the ID list at 0x0C593C (0x0837 ->
    0x0937, entries could no longer be found), offsets at 0x0EEAA2 (0x080C -> 0x090C), 0x0EEB58. Guessed words
    with typed-data evidence are dropped; pointer-like words with typed-pointer evidence are added (0 today).
  None of these showed in the map/battle tours (no wrong reads, no crash).
- Remaining risk list (per language): guess-WEAK-bytelike ~290 (mostly visible byte/halfword data such as
  01 02 03 ... 08 08 09 or 0x080F, 0x0812, ... and never read in the probe) and guess-WEAK-isolated ~535 (mixed:
  real pointers in irregular structs and ARM literal pools, and data such as f1 00 00 08). A pure byte-pattern
  rule is not enough (real function pointer 0x08011D11 has small bytes); next step: combine run-level byte
  patterns with target plausibility (function start, label, file start) and a probe over exactly these words.
- Music sample data (branch `music-sample-data`): `m4a.sample_ranges` walks the song table's voicegroups (12-byte
  voices; DirectSound 0x00/0x08/0x10/0x18 -> WaveData {u16 type, u16 loop flag, u32 freq, u32 loop start, u32 size}
  + size + 1 bytes, the mixer interpolates with sample[size]; programmable wave 0x03/0x0B -> 16 bytes; keysplit 0x40
  and drum 0x80 subgroups recursively; implausible headers rejected). All five versions: 39 waves (37 DirectSound,
  incl. 5 size-0 Camelot synth voices, + 2 programmable), 404 227 bytes, ~0x0FC604-0x15FB77 (USA). `classify` drops
  every guessed word touching it (no format-proven/loaded/typed pointer lies inside). This covers all exclusion-list
  words in sample data (USA 41 of 116, DE 41/118, FR 44/128, IT 45/127, ES 47/127; a few were never guessed) plus
  168-173 more per version that the probe had not seen as byte reads (the mixer reads samples word-wise, so the probe
  saw 32-bit reads and, by chance, "used" on ~12-30 of them: wordmap now puts `sample-data` before the probe).
  Still needed from the lists: 1 word in m4a track data (USA 0x182200) and the byte tables (USA 74: 0x0C5C20..,
  0x0EEA2C, 0x0EECF4, small-number fields in record tables 0x1851E0-0x18D3E4, 0x2468D8, packed sprite 0x2BB454).
