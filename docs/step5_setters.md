# Step 5d: engine literal-pool constants whose use was not proven

Scope: every 32-bit literal-pool word that confirmed engine Thumb code loads (`ldr rX,[pc,#]`) and whose value
lies in GS1's ROM range (0x08000000..+8 MiB). The build relocates all of them (wordmap category `literal`).
`typeflow.Flow(...).lit_use` proved 847 + 305 of the 1 395 USA words; this step closes the rest.

Tool: `tools/litproof.py` (new module, typeflow.py unchanged). Static only, no emulator; the recorded all-words
probe (`build/probe_all/<lang>.txt`) is used as a cross-check.

    python tools/litproof.py "Golden Sun (USA, Europe).gba" build/probe_all/en.txt --list

## 1. Baseline reproduced (typeflow `lit_use`)

| USA | words |
|---|---|
| used as address (addr / arg-deref / jump / swi / dma) | 847 |
| function address (odd, target is confirmed code) | 305 |
| data address only passed to a function or stored | 129 |
| loaded, no use seen | 112 |
| number only (cmp) | 2 |
| **total ROM-range literals** | **1 395** |

Why typeflow misses uses (found while reproducing):
- One merged register state per basic block: a value that reaches its use through a branch join (e.g. four
  `ldr r2,=X; b join` arms), a return value (`ldr r0,=X; bx lr` getters), a callee, `ldm`/`stm` (not modelled), a
  stack slot or a RAM variable is lost.
- **Coverage gap:** typeflow seeds states only at BL targets and stub targets. Functions reached only through
  pointers (handler tables, callbacks) get no state and no "argument k is dereferenced" summary: 5 112 of 21 937
  basic blocks (23 %) in USA. This also limits typeflow's evidence for the other step-5 categories.
- A DMA source (`stm r3!,{r0,r1,r2}` to 0x040000D4) taken from an argument does not enter the deref summaries:
  the copy helper 0x08003FA4 (60 callers) alone hides 37 literals.

## 2. Method (`litproof.Tracer`)

One literal at a time is followed forward from the head of its function (breadth-first, every path, budget
120 000 instructions) as a taint with an offset, through `adds/subs #k`, `mov`, `eors/orrs/bics #1`,
`ands #~1` (Thumb bit), stack slots, `push/pop`, calls (recursively into the callee, depth 4) and returns (getter:
r0 followed after every call site). Events:

| event | meaning (proof of an address) |
|---|---|
| addr | base or index of ldr/str/ldrh/ldrb/ldm/stm (also inside callees) |
| dma / swi / jump | DMA source register, BIOS copy/decompress source (r0), `bx`/`mov pc` |
| arg-deref | argument of a function typeflow knows dereferences it |
| iwram / arm-deref | argument of an ARM routine that reads through it: IWRAM routines (typeflow.IWRAM_DEREF + a short ARM scan, e.g. 0x03000250 `ldm r0,{r2-r4}`) and ARM routines copied to RAM/stack by DMA and called there (0x08001B70, 0x08002298, 0x08002544: `ldrb lr,[r0],#1` / `ldrh r2,[r0],#2`) |
| irq-table | stored into the IRQ vector table 0x030000E0.. (literal pool of the IWRAM image, read by the ARM IRQ handler with `ldr ip,[pc,#]; bx ip`) |
| address-via-ram | stored into a RAM location whose loads (anywhere in the engine) are used as an address / called |
| address-by-identity | compared for equality with a value that is used as an address (a RAM location proven as above, or a register used as a load base in the same block) |
| size | `end - start` with another literal |
| fill-value | the word an IWRAM fill routine writes (0x03000168 = ROM 0x080008D8: `stm r0!,{r2 x8}`): **data** |

RAM locations are symbolic: global (`G a`), word at `d + k` (an object pointer), argument `P j` (resolved through
all direct callers and indirect callers through ROM function tables, `bl _call_via_rN` with rN loaded from a table
of function heads), objects returned by functions (return-value summaries), pointer globals that always hold the
same address (e.g. SOUND_INFO_PTR 0x03007FF0 -> 0x02003050), canonical `G a + k`.

Assumption (stated, not hidden): loop paths are followed once ("first path wins"). For a pool search such as
0x0800C0CC (`[0x03001E64] + i*0x70`) the returned object is the pool's first element, which has the type of every
element. This is what types the setter fields below.

### The setter pattern (main gap)
`0x0800C2D8` (stub 0x08009098) stores its argument r1 into `[r0+0]` and clears the halfword `[r0+4]`; 41 call sites,
many through small wrappers (0x0800C454, 0x0800C46C, ...). Objects come from the allocator 0x0800C150 (stub 0x080090C8) ->
0x0800C0CC = element of the object pool `[0x03001E64]` (64 x 0x70 bytes). The script interpreter 0x0800CACC loads
the same field (`ldr r2,[r6]`, r6 = `[0x03001E64]`) and dereferences it (`ldr r3,[r2,r3]` at 0x0800CB3C) and calls
field +0x6C (`ldr r3,[r6,#0x6c]; bl _call_via_r3` at 0x0800CAFC). Result: 40 animation-script pointers and 2
callbacks per version proven (address-via-ram). The other 5 via-RAM proofs: 3 callbacks in `[0x03001CFC]` (called
at 0x080036C8), the m4a dummy callback 0x080FB791 stored by SoundInit 0x080FA6A0 into SoundInfo+0x28/0x2C/0x30/0x3C
(`[0x03007FF0]` always holds SoundInfo = 0x02003050; SoundMain calls `[r0+0x28]` at 0x0800072A) and 0x080F9C91
stored into SoundInfo+0x20 (called at 0x08000722).

### Identity comparisons (0x080041A4 pattern)
0x080041D8 (163 callers) adds a callback to the list at 0x03001A20 (8-byte entries: pointer, halfword, byte): it
compares its argument r0 with the stored pointers (`ldr r3,[r4]; cmp r3,r0` at 0x080041EE / 0x08004202) and stores
it into a free entry (0x08004220); 0x08004278 (150 callers) removes by the same comparison. 0x08004420 loads the
entries and jumps through them (0x08004444). A literal compared with `[0x03001A20]` / `[0x03001A28]` is therefore
in the same domain as values that are called: 23 (USA) / 24 odd words, targets are Thumb leaf functions.
The 24th (USA) identity proof: USA 0x0EDA74 = 0x080EDE48 is compared (`eors r3,r6`) with r6, a pointer that `ldm r6!`
walks through a ROM table (end-of-table pointer).

## 3. Results (all five versions)

Final categories of all ROM-range literals:

| | USA | DE | FR | IT | ES |
|---|---|---|---|---|---|
| ROM-range literals | 1 395 | 1 403 | 1 401 | 1 405 | 1 407 |
| typeflow proven (address + function) | 1 152 | 1 158 | 1 157 | 1 158 | 1 160 |
| typeflow unproven | **243** | **245** | **244** | **247** | **247** |
| -> proven pointer: direct use (litproof) | 158 | 159 | 158 | 161 | 161 |
| -> proven pointer: via RAM field/global | 47 | 47 | 47 | 47 | 47 |
| -> proven pointer: identity comparison | 24 | 25 | 25 | 25 | 25 |
| -> proven pointer: size end with proven start | 1 | 1 | 1 | 1 | 1 |
| -> size pair, start value proven elsewhere | 4 | 4 | 4 | 4 | 4 |
| -> no runtime effect (callee ignores it) | 1 | 1 | 1 | 1 | 1 |
| -> **proven number (contradiction = bug)** | **1** | **1** | **1** | **1** | **1** |
| -> structural only / unknown | 7 | 7 | 7 | 7 | 7 |

Direct-use proof kinds among the 158 (USA): addr 79, dma 62, arm-deref 9, irq-table 5, arg-deref 3.

Cross-checks:
- Probe: 441 (USA) .. 459 (ES) literals were seen used as an address at runtime; **all** of them are proven
  statically by litproof. No literal was read byte/halfword-wise.
- No literal has both pointer and number evidence.
- All 1 395..1 407 literals are relocated by the current build (`build_gs1_reloc.classify`).

## 4. Contradiction (bug): fill value 0x08080808

| version | word offset | value | load / call |
|---|---|---|---|
| USA | 0x0D39D0 | 0x08080808 | ldr r2 at 0x080D39A2, bl 0x080072FC (bx r6) at 0x080D39A4 |
| DE | 0x0D57D0 | 0x08080808 | same routine |
| FR | 0x0D71D0 | 0x08080808 | same routine |
| IT | 0x0D39D0 | 0x08080808 | same routine |
| ES | 0x0D71D0 | 0x08080808 | same routine |

Evidence (USA): `ldr r6,=0x03000168` (0x080D3992); `ldr r0,[sp,#0x24]; movs r1,#0x80; lsls r1,#7` (0x4000);
`ldr r2,=0x08080808`; `bl _call_via_r6`. 0x03000168 is the IWRAM copy of ROM 0x080008D8:
`mov r3..sb, r2; ... stm r0!, {r2-r9}` loop = fill r1 bytes at r0 with the word r2. The word is written as data
(16 KiB of byte 0x08) in a battle-effect routine (it also writes BLDALPHA and plays sound 0x8D; not covered by the
probe tours). The build relocates it to 0x09080808, so every fourth byte becomes 0x09.
**Proposed change:** do not relocate these five words (e.g. add them to `data/reloc_exclude_<code>.txt`).

## 5. Decision-neutral words

- **No runtime effect** (USA/IT 0x012AF4 = 0x08185000, DE 0x0122F4 = 0x08185E00, FR/ES 0x0122F4 = 0x08187800):
  passed as r1 to 0x08002F0C (DE 0x08002F3C, FR 0x08002F1C, ES 0x08002F6C) = `movs r0,#0; bx lr` (a stripped debug
  function). The value is never read; either decision is harmless. (USA: it equals the address of a function that
  0x0800C1AE calls with `bl`.)
- **Size pairs**: `ldr r0,=END; ldr r3,=START; subs r0,r0,r3; asrs r0,#2; bx lr` (USA 0x08019EBC and 0x08019ED0,
  entry counts of two tables). The result is the same whether both words move or neither; the build moves both.
  START is the address of a table that other engine code dereferences (same value proven at USA 0x01A084,
  0x01A294, 0x01A3C8 and 0x01A4BC), END = START + count*4 is structural.

| version | END word / value | START word / value | END word / value | START word / value |
|---|---|---|---|---|
| USA | 0x019EC8 0x0802A2E0 | 0x019ECC 0x08029EE4 | 0x019EDC 0x0802E108 | 0x019EE0 0x0802DE88 |
| DE | 0x018B3C 0x08028FA4 | 0x018B40 0x08028BA8 | 0x018B50 0x0802CDCC | 0x018B54 0x0802CB4C |
| FR | 0x018DF8 0x08029298 | 0x018DFC 0x08028E9C | 0x018E0C 0x0802D0C0 | 0x018E10 0x0802CE40 |
| IT | 0x019E34 0x0802A40C | 0x019E38 0x0802A010 | 0x019E48 0x0802E234 | 0x019E4C 0x0802DFB4 |
| ES | 0x018EA8 0x080294A0 | 0x018EAC 0x080290A4 | 0x018EBC 0x0802D2C8 | 0x018EC0 0x0802D048 |

(The fifth size word, USA 0x00AD34 = 0x08009D9C, is the end of a code block whose start 0x08009BB8 is a DMA
source: proven, counted above.)

## 6. Remaining structural-only words (7 per version, all relocated by the build)

| USA | DE | FR / ES | IT | value (USA) | why not proven |
|---|---|---|---|---|---|
| 0x095B80 | 0x09921C | 0x09AC0C | 0x095C0C | 0x0809592D | stored into `[obj+0x6C]` (callback field) of an object returned by 0x0808BA1C = `[[0x03001EBC]+0x14+4i]` |
| 0x095F98 | 0x099634 | 0x09B024 | 0x096024 | 0x08095B8D | same |
| 0x0962CC | 0x099968 | 0x09B358 | 0x096358 | 0x0809592D | same |
| 0x0D2C68 | 0x0D4A68 | 0x0D6468 | 0x0D2C68 | 0x080EE188 | r1 of a call through a function pointer read from the stack (`ldr r4,[sp,#0x2c]; bl _call_via_r4` at 0x080D2A26, function 0x080D2464) |
| 0x0FA640 | 0x0FB440 | 0x0FCE40 | 0x0FA640 | 0x080FA1D5 | m4a MPlayExtender (0x080FA55C): `[0x02004000+0x44]` = gMPlayJumpTable[17] (ply_lfos) |
| 0x0FA644 | 0x0FB444 | 0x0FCE44 | 0x0FA644 | 0x080FA1E9 | gMPlayJumpTable[19] (ply_mod) |
| 0x0FA64C | 0x0FB44C | 0x0FCE4C | 0x0FA64C | 0x080FA16D | gMPlayJumpTable[29] (ply_endtie) |

Structural evidence: all six odd values point at valid Thumb code (leaf functions: `ldrh r3,[r0,#6] ... bx lr`,
`mov ip,lr; bl ...`, `push {r4,r5}`). The three m4a words sit in the same store sequence as entries 8, 28, 30-33
(`str r0,[r1,#0x20/#0x70/#0x78/...]`, r1 = 0x02004000), whose values are confirmed functions; that is the m4a
MPlayExtender layout (the 36-entry table is first copied from ROM 0x080FB7A0 by 0x080F9A80). No probe data (menus,
Psynergy and music commands were not toured). Best ideas to close them:
1. Map-object callbacks: type the pointer array `[0x03001EBC]+0x14` by the values stored into it (they come from
   the pool allocator 0x0800C150), then the interpreter's call through `[obj+0x6C]` (0x0800CAFC) proves them.
2. m4a: model the sequencer's indexed dispatch through the RAM jump table 0x02004000 (in the m4a sources
   SoundInfo->MPlayJumpTable; not yet traced here) as a table whose entries are call targets, bounded by the
   0x24-entry copy loop of 0x080F9A80.
3. 0x080EE188: find the producers of the stack function pointer (the single caller of 0x080D2464).

## 7. Odd values whose target is not confirmed code (task item 3)

Among the unproven words: 50 (USA, DE, FR, IT), 53 (ES). USA breakdown:

| kind | words | target |
|---|---|---|
| called / jumped (irq-table 5, via RAM 7, identity 22) | 34 | 32 leaf functions without `push` (first instruction e.g. `bx lr`, `ldr r1,[pc,#]`), 2 longer ones (first unconditional branch after 48 instructions); Thumb, never ARM |
| odd **data** addresses (read with ldrb/ldrsb/ldrh) | 9 | byte tables at odd addresses (e.g. 0x080EE037, 0x080AF2B1) and two Thumb routines copied as data (0x08006ABD, 0x08006F49: `eors #1`, `end - start`, copy to RAM) |
| ARM code copied by CpuSet | 1 | 0x080F9675 `& ~1` -> SoundMain ARM image to 0x03007000 |
| structural only | 6 | see section 6 |

They are not confirmed code because `reloc.strict_code` accepts an odd literal as a root only if it is a BL
target or starts with `push {..., lr}`. The 34 proven call targets (list via `--list`, column odd) could be added
as code roots; that would also extend typeflow's coverage.

## 8. Proposed changes for the coordinator

1. Exclude the fill value 0x08080808 from relocation: USA 0x0D39D0, DE 0x0D57D0, FR 0x0D71D0, IT 0x0D39D0,
   ES 0x0D71D0 (proven data; currently relocated -> wrong fill pattern).
2. No other literal changes; all other ROM-range literals are proven pointers (USA 1 382 of 1 395) or
   decision-neutral (5); 7 remain structural only (relocated, consistent with all structural evidence).
3. Optional typeflow improvements: function heads = blocks without predecessors (23 % of the blocks have no state
   today), DMA/ldm/stm of an argument into the deref summaries, return-value tracking.
