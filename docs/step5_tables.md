# Step 5: the pointer TABLES (`guess-table`)

Scope: the words `tools/wordmap.py` puts in `guess-table` (>= 4 pointer-like words in a row pointing nearby,
relocated by the build on heuristics only), about 7 500 per language in the program area 0 .. code_end. Static
analysis plus the recorded all-words probe (`build/probe_all/<lang>.txt`); no emulator was run.

Tools (new, nothing shared was changed, the build is unchanged):

- `tools/tableflow.py`: `TableFlow`, a subclass of `typeflow.Flow` (details in its docstring). It adds
  - **nested sources** `("sub", parent, stride, off)`: the word at (value of a parent word) + i*stride + off, i.e.
    tables reached through pointers from other tables (two-level and deeper);
  - **return values** (e.g. the sprite getter 0x08185008 returns 0x08185024 + id * 0x14);
  - **argument-path summaries**: "the word at arg k + i*s + off (and deeper) is dereferenced / read narrow /
    receives value V", substituted at every caller (fixpoint over the call graph);
  - **RAM links**: values stored to a RAM word (global or object field, keyed by its access path from a RAM global)
    and loads of the same path elsewhere; what the program does with the loaded value applies to every ROM value
    stored there;
  - stack slots (spills), `ldm`/`stm`, `adr`, pointer walking (`p += 4` in a loop becomes an index), functions
    that are only called through pointers (blocks without predecessors that start with `push {.., lr}`), negative
    index offsets (`4*i - 4`).
  - **bounds** for spreading a proven field over a table: entries from the table start while pointer-like (or 0),
    never over code, up to the next boundary = a code label, an MFT file start or the target of any pointer with
    evidence. Every instance of a nested field must hold a pointer-like word, else the field is dropped (no common
    layout); MFT files are never spread into. Narrow reads through a walked pointer only give candidates.
  - modes: `may=False, gcd=False` = **strict**; `may` = a table word that reaches a control-flow merge on one path
    keeps its identity (`if (!p) p = default`); `gcd` = RAM paths with two strides keyed by their gcd.
- `tools/tableproof.py GS1.gba probe.txt [--list CLASS] [--save r.pkl]`: runs wordmap + three TableFlow modes and
  classifies every `guess-table` word, lists side findings (words of other categories whose evidence contradicts
  the build) and the open runs with the reason. About 2.5 minutes per ROM.

## Result: classes of the `guess-table` words

| class | USA | DE | FR | IT | ES |
|---|---:|---:|---:|---:|---:|
| ptr-code (strict) | 1675 | 1668 | 1670 | 1670 | 1664 |
| ptr-code-may | 4971 | 4975 | 4964 | 4964 | 4979 |
| ptr-code-gcd | 0 | 0 | 0 | 0 | 0 |
| ptr-probe | 0 | 0 | 0 | 0 | 0 |
| DATA-code (contradiction) | 0 | 0 | 0 | 0 | 0 |
| DATA-probe (contradiction) | 0 | 0 | 0 | 0 | 0 |
| CONFLICT | 0 | 0 | 0 | 0 | 0 |
| beyond-count | 0 | 0 | 0 | 0 | 0 |
| structural-partly | 69 | 69 | 69 | 70 | 70 |
| structural | 809 | 817 | 813 | 814 | 810 |
| **total** | **7524** | **7529** | **7516** | **7518** | **7523** |
| proven pointer | 6646 (88.3 %) | 6643 | 6634 | 6634 | 6643 |

Proof route (USA, the others are the same within a few words): deref 1379, RAM link 4985, function argument 209,
jump/call 73.

No `guess-table` word has data evidence (code or probe), so within this category the build's decision (relocate)
is confirmed for every word that has evidence; the contradictions found are in neighbouring categories (below).

### What the proofs are

- **Sprite file (MFT files 17/18 at 0x185000, ~6 340 words)**. The getter 0x08185008 returns the sprite info
  entry 0x08185024 + (id & 0xFFF) * 0x14 (512 entries). Fields: +0x0C frame table, +0x10 animation table,
  +5 animation count, +4..+7 / +8..+0xB bytes.
  - Animation tables (1 377 words, strict): 0x0800BE20: `bl getter; ldrb r3,[r0,#5]; cmp r6,r3; ... ldr r2,[r0,#0x10];
    lsls r3,r6,#2; ldr r0,[r3,r2]; ldrb r2,[r0]` - entry i < count is loaded and dereferenced. Check: every spread
    word lies inside [table, table + 4*count) of some sprite entry (`beyond-count` = 0 in all languages; tables
    shared by two sprites with different counts, e.g. 0x188A9C: sprite 71 count 4, sprite 55 count 12).
  - Frame tables (4 971 words, `may`): 0x0800B868 (sprite object init) stores the frame table pointer
    (`ldr r0,[r6,#0xc]`, or a RAM cache when it is 0 - the may-merge) into object+8 and the animation table into
    object+0xC; the objects live in the array at [0x03001E5C] (stride 0x18) and are linked from map objects
    [0x03001E60] + 0x28 + 4*j. 0x0800AA0C (via 0x0800B168 / 0x0800B388) loads object+8, indexes it with
    object+0x16 * 4 and passes the entry to the frame decoders (0x0800A97C reads it byte-wise). The RAM link
    [0x03001E5C] + 0x18*k + 8 connects store and use. All 310 frame tables (USA) end with a 0 word; 309 are
    followed by non-pointer data (the next sprite's frames), one directly by the next proven target, so the spread
    ends exactly at the terminator.
    The may-merge is sound for pointer evidence (the table word reaches the store on the path where it is not 0);
    the strict mode cannot prove these words because of that single merge.
- **Other engine tables** (~300 words): function/jump tables loaded by Thumb code and called (`bx`, `bl _call_via_rN`,
  e.g. 0x080EE2B4 battle handlers via 0x080D6692), tables passed to functions that dereference the argument
  (argument summaries), records reached through two-level tables (0x00007ABC..: 5-word records).

### Cross-check with the recorded probe (USA, words below code_end)

| | strict | may |
|---|---:|---:|
| pointer-like words proven pointer by code | 4 771 | 10 837 |
| probe wide+used, also proven by code | 1 149 of 2 738 | 1 839 of 2 738 |
| probe narrow-only (190) proven pointer by code | **0** | **0** |
| code data evidence (62 / 66) read wide+used by the probe | **0** | **0** |

Code evidence and runtime evidence never disagree. Of the 207 `guess-table` words the probe read 32-bit without
following them (no runtime verdict), 167 are proven by code and 40 stay open.

## Contradictions with the build (side findings, all in neighbouring categories)

Offsets are GS1 file offsets per language. "level" = weakest mode that shows it.

### 1. Pointer NOT relocated (missed pointer) - frame table of sprite 204

| lang | offset | value | category | evidence |
|---|---|---|---|---|
| USA, IT | 0x2AF154 | 0x082AEF94 | data-noise | frame table of sprite 204 (info entry 0x186014, field +0x0C = 0x082AF154): one entry, then the 0 terminator; RAM link [0x03001E5C]+0x18k+8 -> 0x0800AA0C decoder (level may) |
| DE | 0x2AFF54 | 0x082AFD94 | data-noise | same structure |
| FR, ES | 0x2B1954 | 0x082B1794 | data-noise | same structure |

Proposed change: relocate these words (add to the relocation set). Unrelocated, sprite 204's only frame would be
decoded from TLA data in the merged cartridge.

### 2. Data relocated - sprite info bytes +4..+7 (byte +7 is read with `ldrb`)

0x0800B916 `bl getter; ... ldrb r3,[r0,#7]` (and 0x0800B818): byte +7 of every sprite info entry is a byte field.
Where the word +4..+7 looks like a pointer (+7 = 0x08), the build relocates it and byte +7 becomes 0x09.

| lang | offsets (value) | category |
|---|---|---|
| USA, IT | 0x185208 (08000301), 0x186400 (0800030B), 0x186414 (0800040B), 0x186770 (0800040B), 0x187774 (08000201) | guess-WEAK-bytelike |
| DE | 0x186008 (08000301), 0x187200 (0800030B), 0x187214 (0800040B), 0x188574 (08000201) | guess-WEAK-bytelike |
| FR, ES | 0x187A08 (08000301), 0x188C00 (0800030B), 0x188C14 (0800040B), 0x189F74 (08000201) | guess-WEAK-bytelike |

0x186770 (USA/IT) is also read narrow by the probe (62 / 66 narrow reads, 0 wide) - it is not in the exclusion
list because that list predates the all-words probe. The entries of these sprites with +7 = 0x08 that the probe saw
are already excluded (probe-data). Proposed change: exclude these words (level strict).

### 3. Data relocated - first word of a compressed sprite frame

| lang | offset | value | category | evidence |
|---|---|---|---|---|
| USA | 0x301EC4 | 0x08000003 | guess-WEAK-bytelike | frame table entry 0x301F20 points here; the decoder reads the frame byte-wise (level full) |
| IT | 0x301ECC | 0x08000003 | guess-WEAK-bytelike | same |
| DE | 0x302CC4 | 0x08000003 | guess-WEAK-bytelike | same |
| FR, ES | 0x3046C4 | 0x08000003 | guess-WEAK-bytelike | same |

A frame pointer points at compressed bytes, so the word there is data; relocation changes byte 3 (0x08 -> 0x09).
Proposed change: exclude.

### 4. Probable data relocated - byte / halfword arrays (extent known only from bounds)

Strict code reads, but through an index of unknown range, so the array length comes from the next boundary
(class "bytes"; not counted as proof, listed for review). Values look like byte data.

| lang | array (reader) | relocated words |
|---|---|---|
| USA | halfwords at 0x09C614 (read at 0x0808B06A) | 0x09C65C, 0x09C694, 0x09C6CC, 0x09CB84, 0x09CCD4 |
| USA | halfwords at 0x0EEADD / 0x0EED7E (0x080DB530 / 0x080E34B6) | 0x0EEAE0, 0x0EED88 |
| USA | bytes at 0x0F11BD (character widths after "GOLDEN SUN STAFF CREDITS", read at 0x080F0886) | 0x0F11C0, 0x0F11DC, 0x0F11E0, 0x0F11E8, 0x0F11EC, 0x0F11F0, 0x0F11F4 |
| DE | 0x09FD7C (halfwords) / 0x0F08DD / 0x0F0B7E / 0x0F2839 (bytes) | 0x09FDC4, 0x09FDFC, 0x09FE34, 0x0A01D0, 0x0A020C, 0x0A02EC, 0x0A043C, 0x0F08E0, 0x0F0B88, 0x0F283C, 0x0F2858, 0x0F285C, 0x0F2864, 0x0F2868, 0x0F286C, 0x0F2870 |
| FR | 0x0A176C / 0x0F22DD / 0x0F257E / 0x0F4241 | 0x0A17B4, 0x0A17EC, 0x0A1824, 0x0A1BFC, 0x0A1CDC, 0x0A1E2C, 0x0F22E0, 0x0F2588, 0x0F4244, 0x0F4260, 0x0F4264, 0x0F426C, 0x0F4270, 0x0F4274, 0x0F4278 |
| IT | 0x09C76C / 0x0EEADD / 0x0EED7E / 0x0F1245 | 0x09C7B4, 0x09C7EC, 0x09C824, 0x09CCDC, 0x09CE2C, 0x0EEAE0, 0x0EED88, 0x0F1248, 0x0F1264, 0x0F1268, 0x0F1270, 0x0F1274, 0x0F1278, 0x0F127C |
| ES | 0x0A176C / 0x0F22DD / 0x0F257E / 0x0F4235 | 0x0A17B4, 0x0A17EC, 0x0A1824, 0x0A1CDC, 0x0A1E2C, 0x0F22E0, 0x0F2588, 0x0F4238, 0x0F4254, 0x0F4258, 0x0F4260, 0x0F4264, 0x0F4268, 0x0F426C |

The 0x09C614 records are 0x38-byte records with byte arrays (`23 00 01 00 07 00 ...`), the 0x0F11BD table is a
per-character byte table; both very likely data (the categories are guess-WEAK-*, owned by another helper).

## What remains open (`structural`, USA 878 words in 44 runs; the other languages have the same runs)

| reason | USA words | examples / idea to close |
|---|---:|---|
| Thumb code loads the base, the use is not traced | 589 | 0x029EE4 (255, count = (0x0802A2E0-0x08029EE4)/4 computed by 0x08019EBC), 0x02DE88 (160), 0x029E00 (43), 0x0308A0 (32), 0x029B68 (13), 0x031864 (8): one entry is stored to [[0x03001E94]+0x604]; no confirmed Thumb code reads that field (reader not reached from the roots, or ARM). 0x007320 (14 x 0x08003009): IRQ table, DMA-copied to 0x030000E0 by 0x08003024 (count 14), presumably read by the ARM IRQ handler. 0x0FB7A0 (36 function pointers): copied to RAM by 0x080F9A84 (count 0x24), the copy goes through a check call that may clear r3 - needs "register preserved on some path" call summaries. |
| base is a literal of Thumb code outside the confirmed code | 211 | 0x0AA18C (57), 0x0AA494 (32), 0x0ABD30 (28), 0x0ADC78 (19), 0x0BC30C (22), ...: literal pools of functions not reached from the trusted roots. Extending the roots (function pointers proven by this analysis, e.g. the battle handler tables) and re-running would cover them. |
| no reference found | 48 | 0x007A8C, 0x00AD40, 0x0D23D0, 0x0D6FEC, 0x0D7BD8, 0x0D822C, 0x0E2518, ...: reached by offset arithmetic or unreached. |
| other entries of the run proven, these not (bound) | 28 | 0x188ACC..0x188AD8 (4 words, each 0x08188ACC) after the 12-entry animation table 0x188A9C, 0x1897EC.. (5 x 0x081897EC, 5 x 0x08189800) after table 0x1897D8: blocks pointing at themselves, no sprite entry points at them; 0x007ABC.. record tails. Unreachable by the code paths found; relocating them is harmless if unused. |
| ARM literal | 8 | 0x0F0124: table used by an ARM routine (ARM code is not analysed). |
| **probably data** | 2 | 0x1B76BC (0x082F7EDD) and 0x1DC590 (0x08100D07): 2 words before a frame table, after the last frame of that sprite, i.e. most likely the tail of the last compressed frame. Relocating them would corrupt that frame. Proof needs a port of the sprite frame decoder (type-2 sprites decode through the RAM routine called via 0x080072F0) to get the exact compressed length; then also all frame tables could be checked by tiling (frames exactly fill the space before their table). Same in all languages. |

Probe: 40 of the open words were read 32-bit but never followed (no verdict), none was read narrow, the rest was
not read at all (coverage of the sprite file is 26 % of its 256-byte blocks; menus, Psynergy, shops and scenes
were not toured).

## Notes on strictness

- `ptr-code` (strict) is code use in the typeflow sense plus nested/RAM/summaries, without may-merges and gcd keys.
- `ptr-code-may` relies on one documented may-merge (frame tables); pointer evidence through a may-merge is sound
  as long as the path is feasible (here: the frame table pointer is not 0, true for 310 tables).
- RAM links key RAM words by access path from a global; aliasing through different paths only loses proofs. A
  path conflation (two object types behind the same key) could in principle mislink; the frame-table link was
  checked by hand (both ends use the same sprite object layout: +7 type, +8 frames, +0xC animations, +0x16 frame).
- Data evidence from narrow reads through a walked pointer (stride > 0) is reported as a candidate only
  (`TableFlow.walked`); it is wrong for walkers over mixed records (e.g. 0x007ABC records) and is not used.
