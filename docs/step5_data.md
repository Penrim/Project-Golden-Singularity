# Step 5 (data part): byte-like guesses, data noise, SUSPECT words, exclusion lists

Tool: `tools/dataproof.py GS1.gba build/probe_all/<lang>.txt [--list [--all]] [--json OUT]` (about 3 minutes per
language, static only; it uses the recorded all-words probe and file tour, no emulator).
Result tables (all five languages): `docs/step5_data_words.tsv` (every word of the categories below with verdict and
evidence) and `docs/step5_data_contradictions.tsv` (every word where the evidence contradicts the build).

## What the tool proves, and how

| source | what it covers | grade |
|---|---|---|
| sprite parser | sprite table (lookup `T + 20 * (id & 0xFFF)`, USA 0x08185008 via the engine stub 0x08185000): 512 records (the table ends where the first anim script starts), anim tables (count = record +5, checked by the code), anim scripts (byte pairs {op, arg}, interpreter USA 0x0800AA94, commands 0xEF..0xFF through the jump table 0x0800AAC8), frame tables and every frame | format |
| sprite frame decoders | per record format (+0xA, dispatch USA 0x0800AE8E): 1 = GS format 0/1 (ARM 0x08002544; gsfs plus the routine's minimum offset width of 1 bit), 3 = two-stream LZ (IWRAM 0x030005C0 / Thumb 0x0800A97C; first u16 = control-stream offset, 0 = a raw stream follows), 0 = raw stream (ARM 0x08009BB8). 5 752 of 5 753 frames (USA) decode exactly to the next frame or table | format |
| m4a track streams | track bytes from start to FINE/GOTO (sound engine reads them with ldrb), GOTO/PATT/REPT pointer bytes excluded | format |
| decoder blobs | a ROM constant passed as source to an unpack wrapper (`fileflow._copy_routines`: GS 0/1, graphics LZ; new: halfword LZ, ARM USA 0x08002298 run from the stack by 0x080052F4) decoded to its end | format |
| AccessFlow (typeflow subclass) | code coverage + instructions after `mov ip, pc; bx rN` (IWRAM call idiom) + switch cases (`ldr; mov pc` with cmp bound); every load logged with width and table source; `(i << k) + c` indexes; index functions run concretely (masks, clamps: e.g. USA 0x080773D8 `T + 0x54 * clamp(id - 8, 0xF9)`); a narrow read of any byte of a word = data | code (exact / parser / mask bound) |
| same, label bound | field spread up to the next label (as typeflow), stopped at anything else proven (music, samples, text, literals, sprite area); fill-pattern constant 0x08080808 is not a label | weak code (label) |
| same, byte index | byte table read `ldrb [T, rX]` with an unknown index, up to the next label | weak code (byte-index) |
| stubs / callbacks | engine stub jumped to by map code or confirmed code; literal = confirmed function + 1 passed as argument | code |
| file tour | `fileverify.verify` for words inside MFT files | format / probe |
| probe | all-words probe: narrow-only = data, wide + used = pointer (m4a pointers excluded: read byte-wise by design) | probe |

## Counts (pointer-like words of the categories, all five languages)

"static" = format or code evidence (exact / parser / mask bound); a word with several sources counts once.

| group | verdict | USA | DE | FR | IT | ES |
|---|---|---|---|---|---|---|
| guess-WEAK-bytelike (relocated) | data: static | 118 | 114 | 114 | 116 | 114 |
| | data: weak code (label) | 21 | 21 | 21 | 21 | 21 |
| | data: weak code (byte-index) | 19 | 21 | 18 | 16 | 17 |
| | pointer: static | 13 | 11 | 13 | 16 | 11 |
| | unproven | 12 | 13 | 9 | 8 | 13 |
| data-noise (not relocated) | data: static | 297 | 297 | 297 | 296 | 298 |
| | data: weak code (label) | 4 | 5 | 5 | 4 | 5 |
| | data: weak code (byte-index) | 13 | 10 | 13 | 13 | 12 |
| | **pointer: static (missed pointer)** | 1 | 1 | 1 | 1 | 1 |
| | unproven | 21 | 21 | 22 | 19 | 22 |
| SUSPECT-data-hits-target | data: static | 0 | 2 | 0 | 0 | 0 |
| | data: weak code (label) | 1 | 0 | 0 | 1 | 0 |
| SUSPECT-file-hits-target | data: static (file format proof) | 10 | 6 | 8 | 12 | 9 |
| | unproven (file 20, see below) | 7 | 7 | 7 | 7 | 7 |
| exclusion list, in m4a samples | data: static | 41 | 41 | 44 | 45 | 47 |
| exclusion list, other | data: static | 70 | 72 | 73 | 73 | 73 |
| | data: weak code + probe | 3 | 4 | 4 | 3 | 4 |
| | data: weak code (byte-index) only | 1 | 0 | 3 | 4 | 2 |
| | data: probe only | 1 | 1 | 4 | 2 | 1 |

No word got both data and pointer evidence (no conflicts), and no word of the categories has probe "used".

## Contradictions with the build (bugs)

Totals: USA 294, DE 292, FR 289, IT 288, ES 287. Full list with offsets, values and evidence per language:
`docs/step5_data_contradictions.tsv`. They are not only in my categories: the sprite parser also covers words the
build relocates as guess-table / guess-plausible / guess-WEAK-isolated.

| build category | what the word is | evidence | USA | DE | FR | IT | ES |
|---|---|---|---|---|---|---|---|
| guess-WEAK-bytelike | anim script bytes | static | 109 | 107 | 107 | 107 | 107 |
| guess-WEAK-isolated | anim script bytes | static | 54 | 54 | 54 | 53 | 54 |
| guess-plausible | anim script bytes | static | 32 | 33 | 32 | 32 | 32 |
| guess-WEAK-isolated / -plausible / -bytelike / guess-table | packed sprite frame bytes | static | 41 | 39 | 41 | 41 | 40 |
| guess-WEAK-bytelike | sprite record +4 (u8 x4, +7 read with ldrb) | static | 5 | 4 | 4 | 5 | 4 |
| guess-WEAK-isolated | m4a track stream bytes | static | 3 | 3 | 3 | 3 | 3 |
| guess-WEAK-isolated / -bytelike / -plausible | packed blob passed to a decoder | static | 4 | 4 | 3 | 4 | 3 |
| guess-WEAK-bytelike / -isolated / -plausible | byte/halfword tables (item table +0 etc.) | weak code (label) | 23 | 23 | 23 | 23 | 23 |
| guess-WEAK-bytelike / -isolated / -plausible | byte tables, unknown index | weak code (byte-index) | 22 | 24 | 21 | 19 | 20 |
| **data-noise** | **frame-table pointer, not relocated** | static | 1 | 1 | 1 | 1 | 1 |

Effect of relocating a data word: byte 3 changes 0x08 -> 0x09. Examples (USA):
- anim scripts: 0x18D3A0 `00 08 01 08` (frame 1 shown 8 -> 9 ticks), 0x18782C `0A 50 19 08`; 195 words: animation
  timing of many sprites changes slightly.
- sprite frames: 41 words inside packed frames (e.g. 0x2C30C8..0x2C3108 in a format-0 frame, 0x1B76BC just before
  the frame table 0x1B76C4): wrong pixels/runs, like the known Isaac glitch (0x2BB454).
- sprite records +4: 0x185208, 0x186400, 0x186414, 0x186770, 0x187774 (+7 = 08 -> 09: signed y offset copied to
  object +0x22 at 0x0800B818, sprite 1 px off).
- m4a: 0x1813C4, 0x182158, 0x1821AC (`82 D2 58 08` = wait, note 0x58 velocity 8 -> 9).
- decoder blobs: 0x09E5C0, 0x09E638, 0x09E63C (halfword-LZ blob 0x09E4CE-0x09E680, decoded exactly to the next
  label), 0x0A00E8 (graphics-LZ blob 0x0A00B8-0x0A0107).
- item table (44-byte records, 0x07B6A8 + 0x2C * (id & 0x1FF), field +0 read with ldrh at 0x080B19D4, +2/+3 with
  ldrb): 0x07D908.. 0x07E098 (`00 00 06 08`, price 0, +3 = 8 -> 9) and 0x07DF0C.

**Missed pointer (all five languages):** sprite record 204 (32x64) has frame table +0x0C -> a table with one
entry; the record word is relocated (guess-WEAK-isolated) but the table entry is not (data-noise), so after the
move the sprite's frame pointer still says 0x08xxxxxx (the TLA half of the merged cartridge):

| lang | record +0x0C (relocated) | table entry (NOT relocated) | value | frame |
|---|---|---|---|---|
| USA | 0x186020 | 0x2AF154 | 0x082AEF94 | raw stream 0x2AEF94-0x2AF151 |
| DE | 0x186E20 | 0x2AFF54 | 0x082AFD94 | |
| FR | 0x188820 | 0x2B1954 | 0x082B1794 | |
| IT | 0x186020 | 0x2AF154 | 0x082AEF94 | |
| ES | 0x188820 | 0x2B1954 | 0x082B1794 | |

Proposed build change (not made): relocate the table entry; drop every word with "data: static" from the
relocation set; the weak-code words (label / byte-index) are visibly byte data as well (examples: fade table
0x0C5C10 `0F 0E .. 00 04 06 07 08 08 ..` read with ldrsb, position tables 0x0EEA90.. read with ldrb) and are best
dropped too, but they rest on the next-label bound only.

## Exclusion lists: from input to check

Every exclusion word is explained by evidence (USA: 41 m4a sample words + 70 static + 3 weak code + probe + 1
weak code + 1 probe only). With the sprite parser, the m4a track/sample formats and the code reads, the lists are
derivable except for these words:

| lang | word | evidence |
|---|---|---|
| all | fade table 0x0C5C20/24 (USA), position tables 0x0EEA2C, 0x0EECF4 (+FR/ES 0x0F18DC/E0, IT 0x0EE0D0..E0) | byte table read with unknown index (byte-index) |
| all | USA 0x0C5E28 (DE 0x0C8440, FR/ES 0x0C9E40, IT 0x0C5E40) `00 0E 02 08` in a 16-byte record table | probe only |
| FR | 0x032BD4, 0x032F40, 0x032F44; IT 0x033C74 | probe only (font glyph rows, see below) |

Proposal: build the exclusion set from `dataproof` (static data verdicts) and keep `reloc_exclude_<code>.txt` as
a check that must be a subset of it plus the probe-only words above.

## Remaining unproven (USA; other languages the same words at their offsets)

- 0x0329B4, 0x03344C, 0x033B2C/C6C/D4C and data-noise 0x032390..0x03336C: font glyph records (32 bytes, table
  0x032224 indexed `(c - 0x20) * 32`; row halfwords are read through an incremented pointer, which typeflow does
  not follow). Visibly 16-bit glyph rows.
- 0x033E84/88: byte ramp `00 01 01 02 .. 08 08 07` after the 8-pointer table 0x033E40.
- 0x00684C (0x08001000): literal of unconfirmed code (0x080067FA) passed as source address to 0x080063BC, next to
  a shift-built 0x08000000 (`0x80 << 0x14`) - a pointer by hand; note the companion address is not relocatable.
- 0x021E44 (0x08021E15): callback literal of an unconfirmed function at 0x021E2C - pointer by hand.
- 0x015334, 0x08A06C: engine stubs that nothing visible jumps to (stub blocks; 0x08A25C is proven via map code 881).
- 0x02D6C0: inside the bit-packed area 0x02A2E4-0x02DE80 (variable records behind the 255-pointer table 0x029EE4,
  read through a RAM cursor by 0x0801A5A4); data-noise 0x02BA88..0x03058C are in the same kind of area.
- data-noise 0x019CD8, 0x025644/0x025DF8, 0x0D641C: Thumb instructions in functions that are not in the confirmed
  coverage; 0x0F96E0: ARM code copied to IWRAM (m4a); 0x031B5C/D68, 0x084354, 0x09E680: tables behind labels with
  no resolvable read.
- SUSPECT-file 0x322FBC..0x32357C: file 20 (8x8 1-bpp glyphs by structure), no code use found and not requested
  in the file tour.

Best idea to close them: follow pointer increments in typeflow (`ldrh rX, [rP]; adds rP, #2` loops) for the glyph
tables, and add the functions reached only through stub blocks / callbacks as roots (with a check that their code
does not run into tables), which would turn the code-like noise and the callback literals into proven words.
