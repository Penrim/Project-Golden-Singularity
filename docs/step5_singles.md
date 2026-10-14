# Step 5b: short runs and single words (guess-plausible, guess-WEAK-isolated)

Scope: the words `tools/wordmap.py` puts in `guess-plausible` and `guess-WEAK-isolated` (USA 897 + 510 = 1407;
DE 1410, FR 1405, IT 1402, ES 1407). The build relocates all of them. Every word now has a class with evidence
(`tools/singles.py`). Static analysis and the recorded all-words probe only; no emulator runs.

Tool: `python tools/singles.py GS1.gba build/probe_all/<lang>.txt [--usa USA.gba] [--list CLASS] [--tsv FILE]`
(about 40 s per ROM). `docs/step5_singles_words.tsv` lists every contradiction and every unproven word for all five
languages. Columns: lang, GS1 offset, value, wordmap category, class, evidence. It also lists the contradictions the
sprite evidence finds in other categories. Proven pointers are not listed, because the build already relocates them.

## What the module adds (evidence sources)

1. **Switch tables** (`extended_code`). `reloc.strict_code` stops at `mov pc, rX`. In GS1 the case blocks of a
   jump table are often the only way into a function. A jump table counts as bounded when it is preceded by
   `cmp rI,#N` with `bhi`, `bls`, `bcs` or `bcc`. The case blocks of every bounded table are added as roots, and
   this repeats until nothing changes. The result is 72 tables and 1557 cases (USA). Confirmed code grows from
   170,762 to 216,272 halfwords. Words that this code loads PC-relative are literals. Words that fall inside this
   code are instructions.
2. **Engine jump tables** (`stub_chains`). Every engine code file starts with an export table of
   `ldr r4,[pc,#0]; bx r4; .word fn`. File 0's table follows the cartridge header at 0xC0. The only reader of the
   word is the `ldr`, followed by a jump to the value. This is the format `reloc.stub_targets` already trusts. For
   each word the evidence notes any BL from confirmed code, any map-code import stub, any ARM read, and probe
   execution. Map code reaches the engine only through these stubs: all 326 distinct imports hit an engine stub.
3. **ARM routines** (`arm_entries`, `arm_literals`). The entries are:
   - the cartridge entry at 0x080003C0;
   - routines that confirmed Thumb code DMA-copies to RAM (a literal whose typeflow use is "dma");
   - IWRAM-image routines called through `_call_via_rX`.

   The module does recursive descent over the ARM code and finds `ldr rX,[pc]` whose register is next used as a
   memory base or branch target.
4. **Return values** (`RetFlow`, a typeflow subclass). When every return of a function leaves r0 as
   `table + i*stride`, a ROM constant, or one loaded ROM word, callers receive that value. This turns
   `get_sprite_desc(i)` (USA 0x08185008, behind the stub at the start of file 0x185000) into the table
   0x08185024, stride 20. Its bound is 512 entries: the first entry whose pointer fields stop being ROM/0 is 512,
   and the first target of those fields is 0x081879A8, after the end at 0x08187824.
5. **Sprite data** (hand-traced in USA; the module finds the same patterns automatically in every version):
   - Descriptor +16 is used as an address (typeflow deref). It is the **animation list**. `set_anim(i)` at
     0x0800BA0C checks `i < desc[5]`, then loads `list[i]` and stores it to object+0x10. The interpreter at
     0x0800AA94 reads object+0x10 byte by byte, as 2-byte commands: op/arg, with ops 0xEF..0xFF going through a
     17-entry jump table, 0xEF/0xF1 stopping and 0xFD jumping. List lengths found from the structure equal
     `max desc[5]` for 362 of 364 lists. Script extents come from `anim_script_bytes`.
   - Descriptor +12 is stored to object+8 (0x0800B83C, 0x0800B894, 0x0800BC16). Object+8 is indexed as a word
     list: `ldr r2,[obj,#8]; ldr r0,[r2+frame*4]` (0x0800AE96 and three more sites). The entry goes in r0 to the
     frame decoders: 0x08005340 for GS format 0/1, 0x0800A97C (decode3) for type 3, or a RAM routine. This is the
     **frame list**: 310 lists, each ending with a 0 word.
   - Frame streams count as data only when the decoder emulation ends exactly at the next frame, within 3 bytes of
     padding:
     - GS format 0/1 frames via `gsfs.decompress_span`, which must also decode to width*height = desc[0]*desc[1];
     - the stage-1 literal and control streams of decode3 (`frame_extent_c3`, ported from 0x0800A97C).
6. **Hand-verified words** (`MANUAL`). These are mapped to the other versions by the 16 bytes on each side.
   - 0x0EE9F4: a 3-entry halfword table. The index is `x mod 3`, computed by IWRAM 0x030003AC.
   - 0x0F00F4: an ARM self-relocation base.

**Check against the recorded probe.** No word the probe saw used as a pointer lands in a script or frame stream.
No word the probe saw read byte-wise lands in a sprite list. Over all words of the sprite area, USA, `probe-pointer`
gives 569 anim-list and 690 frame-list entries, and `probe-data` gives 47 script and 24 stream words.

## Counts (all five languages)

| class | evidence | en | de | fr | it | es |
|---|---|---:|---:|---:|---:|---:|
| pointer:jump-table | format: engine export stub | 357 | 359 | 355 | 356 | 357 |
| pointer:field | sprite descriptor +12/+16 (512 entries) and table 0x0A012C | 424 | 424 | 424 | 424 | 424 |
| pointer:literal | loaded by switch-confirmed code, used as an address | 103 | 101 | 103 | 103 | 103 |
| pointer:literal-passed | loaded by switch-confirmed code, value passed on (same level as wordmap `literal`) | 91 | 91 | 89 | 91 | 91 |
| pointer:frame-list | 0-terminated frame list | 91 | 91 | 92 | 91 | 91 |
| pointer:anim-list | animation list, index < desc[5] | 91 | 90 | 90 | 90 | 90 |
| pointer:arm-literal | ARM code (0x400 entry, 0xA30C, 0x157F0, 0xF00F4) | 4 | 4 | 4 | 4 | 4 |
| **proven pointer, total** | | **1161** | **1160** | **1157** | **1159** | **1160** |
| data:anim-script | read byte-wise by the interpreter | 86 | 87 | 86 | 85 | 86 |
| data:frame-stream | frame decoder stream | 22 | 19 | 21 | 22 | 20 |
| data:code | Thumb instruction | 3 | 3 | 3 | 3 | 3 |
| data:field | halfword table (MANUAL) | 1 | 1 | 1 | 1 | 1 |
| **proven data = contradictions, total** | | **112** | **110** | **111** | **111** | **110** |
| structural:unreached-literal | literal pool of code no confirmed code reaches | 63 | 65 | 64 | 60 | 61 |
| structural:in-frame-data | between two frames, decoder end not verified | 15 | 16 | 16 | 15 | 16 |
| structural:loaded-32bit | loaded 32-bit, use not traced | 5 | 5 | 5 | 5 | 7 |
| **structural only, total** | | **83** | **86** | **85** | **80** | **84** |
| **unknown** | | **51** | **54** | **52** | **52** | **53** |

## Contradictions: words the build relocates but which are data (bugs)

Offsets are GS1 offsets. All of these words are relocated today.

- **Thumb code, 3 words per version.** Each is the same `lsrs #1` → `lsrs #5` pattern found earlier. The code sits
  in switch case blocks, so `strict_code` misses it.
  - USA: 0x019364 (`adds r2,r2,r3; lsrs r2,r2,#1`), 0x0BBF0C (`beq; lsrs r1,r1,#1`) and
    0x0EA7A0 (`lsls r3,r3,#4; lsrs r2,r0,#1`).
  - DE: 0x017F80, 0x0BE524, 0x0EC5A0.
  - FR: 0x01823C, 0x0BFF24, 0x0EDFA0.
  - IT: 0x019278, 0x0BBF24, 0x0EA7A0.
  - ES: 0x0182EC, 0x0BFF24, 0x0EDFA0.
- **Halfword table, 1 word per version.** The 3-entry halfword table 0x080EE9F2 is read by `ldrh` at 0x080D8076
  with index `i mod 3`. The word holds entries 1 and 2 (0x0480, 0x0810 → 0x0910).
  - USA 0x0EE9F4, DE 0x0F07F4, FR 0x0F21F4, IT 0x0EE9F4, ES 0x0F21F4.
- **Sprite frame streams** (compressed graphics):
  - USA: 192658 19B71C 19EB30 19F648 1A15F0 1BB4D0 1D9CBC 1E5948 2298A0 22A438 231840 242A04 2C4924 30C9F4 310D74
    311AF8 315D4C 318958 318A10 31AB58 31AB5C 31EC98.
  - DE: 193458 19F930 1A0448 1BC2D0 1DAABC 22A6A0 22B238 243804 2AC74C 2C5724 30D7F4 311B74 3128F8 316B4C 319758
    319810 31B958 31B95C 31FA98.
  - FR: 194E58 19DF1C 1A1330 1A1E48 1B1C78 1BDCD0 1DC4BC 22C0A0 22CC38 245204 2C7124 30F1F4 313558 313574 3142F8
    31854C 31B158 31B210 31D358 31D35C 321498.
  - IT: as USA, except 30C9FC 310D7C 311B00 315D54 318960 318A18 31AB60 31AB64 31ECA0.
  - ES: as FR, without 313558.
- **Animation scripts**: USA 86 words, from 0x18782C to 0x18D50C. One example is 0x18D40C = `00 08 01 08`, the
  commands frame 0 for 8 ticks and frame 1 for 8 ticks; relocation makes the second duration 9. Other versions:
  DE 87, FR 86, IT 85, ES 86. The TSV lists them all (class `data:anim-script`).

**The same evidence decides words in other helpers' categories.** These are in the TSV with their wordmap
category.

- `guess-WEAK-bytelike` animation-script words: 109 USA, 107 in each other version. Data, relocated: bugs.
- `guess-WEAK-bytelike` frame-stream words: 3 per version. Data, relocated: bugs.
- `guess-table` frame-stream words: 2 per version. Data, relocated: bugs.
- **One real pointer that is NOT relocated (`data-noise`).** It is the only frame of sprite descriptor 204
  (USA 0x08186014: 32×64, type 3). The probe never read it.
  - USA 0x2AF154 = 0x082AEF94, DE 0x2AFF54, FR 0x2B1954, IT 0x2AF154, ES 0x2B1954.
- **Pointers proven for the guess-table helper** (USA counts):
  - 4971 `guess-table` frame-list entries and 1377 `guess-table` anim-list entries.
  - 91 and 25 `guess-WEAK-*` list entries.
  - Data in the same area, already decided by the probe: 47 `probe-data` script words and 24 stream words.

## Remaining unproven words (USA; the other versions are similar)

- **structural:unreached-literal (63).** These are literal pools of Thumb functions that decode cleanly from a
  `push {..,lr}`, with a return or branch before the pool, but that no confirmed code reaches. Examples are
  0x08022A7C, 0x080CB4EC, 0x080DC1EC and 0x080FA3F0. Also here are 2 ARM literals in the DMA routine 0x0800A494,
  whose only copier 0x0800D304 is itself unreached. If such code really is dead, relocating its literals is
  harmless. The callers are probably function pointers built at run time.
- **structural:in-frame-data (15).** These lie between two frames of type-3 sprites with h = 0 (stage 2 is a RAM
  routine taken from object+0xB8, not ported) and of type-0 frames. They are almost certainly data.
- **structural:loaded-32bit (5).** These are the 3-entry tables 0x08029A10 and 0x08029ACC and the word 0x08073968
  (returned by 0x08021BC8). Confirmed code loads them 32-bit and stores them to RAM.
- **unknown (51)**, by group:
  - 0x007A4C–0x007C60 (11): records next to the engine structs 0x08007ABC and 0x08007C10 (odd function
    addresses, and 0x08007C10 pointing at that struct).
  - 0x029A10 and 0x029A14.
  - 0x029D9C, 0x02CFAC–0x02DA84 (11), 0x02E6C0 and 0x031C38: bit-packed data in file 0x15000.
  - 0x032E58–0x032F98 (6): offset +0x14 inside the 32-byte records of 0x08032224.
  - 0x07DF0C, 0x0EEC5C, 0x0EEC60, 0x0EED88, 0x0F1828, 0x09E5C0, 0x09E638, 0x09E63C, 0x1813C4, 0x182158 and
    0x1821AC: single words in byte tables or bitmaps.
  - 0x0910E4 and 0x09E8A4–0x09FF30 (6): records with odd callback addresses, in tables passed as arguments.

  Apart from 0x09FE08 (262 wide reads, none used), the probe never read any of them. The tour skipped menus,
  Psynergy, shops and story scenes.

**How to close them.**
1. Extend typeflow to follow RAM object fields: a store of a ROM-derived value to `[obj,#K]` and a later load of
   `[obj,#K]`, with the object identified by how it is reached (as done by hand for the sprite objects). Also
   summarise function arguments that are stored and later dereferenced. This would settle the loaded-32bit words,
   the callback records and the 0x08007C10 structs.
2. Port the stage-2 sprite decoder (the RAM routine at [obj+0xB8]) to verify the 15 in-frame words.
3. Run a targeted probe of menus, Psynergy, summons, shops and story scenes, to cover the unreached functions and
   the unknown tables.

## Proposed build changes (not applied; for the coordinator)

1. Use `singles.extended_code` in place of `strict_code` for the build's `in_code` and `loaded` sets. This drops
   the 3 code words and turns about 194 more guesses into literals.
2. Stop relocating the `data:*` words listed in the TSV (all versions):
   - 3 code words;
   - 1 halfword-table word;
   - about 20 frame-stream words and about 86 animation-script words from these two categories;
   - plus the `guess-WEAK-bytelike` and `guess-table` script and stream words.

   This could be done either through a `singles.classify()` call in `build_gs1_reloc.classify`, or by adding the
   offsets to `data/reloc_exclude_<code>.txt`.
3. Relocate the frame-list word 0x2AF154 (USA) and its equivalents (see above).
