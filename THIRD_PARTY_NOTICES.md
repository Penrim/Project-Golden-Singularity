# Third-party notices

## gs2-randomiser2 (Karanum) — MIT

`tools/gsfs.py` (Golden Sun compression formats 0 and 1, decoding) and `tools/compress.py` (format 1 encoding)
are ports of code from <https://github.com/Karanum/gs2-randomiser2> (`modules/decompression.js`, `compressC1`).

```
MIT License

Copyright (c) 2024 Karanum

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Python packages (installed by the user, not distributed here)

| Package | Use | Licence |
|---|---|---|
| Pillow | images | MIT-CMU (HPND) |
| capstone | disassembler (finds addresses in the game code) | BSD-3-Clause |
| keystone-engine (developers only) | assembler for the small hooks | GPL-2.0 — not distributed; only its output (machine code bytes in `data/asm_cache.json`) is included |

## Tools used during development (not distributed)

- Arm GNU Toolchain (GCC) — compiles `cart/runtime.c`; the compiled result is in `cart/prebuilt/`.
- mGBA (MPL-2.0) — emulator used for automated tests.
- ComfyUI (GPL-3.0) with the **Z-Image Turbo** model (Tongyi-MAI, Apache-2.0) — generated the middle part of the
  start-screen panorama (`art/panorama_patch.png`); settings and prompt in `art/README.md`.
- ComfyUI with the **MOSS-Image** model (OpenMOSS, Apache-2.0; ComfyUI repackage Comfy-Org/MOSS-Image) — generated
  the background of the "Chapter 2" card (`art/card_bg.png`); settings and prompt in `tools/bootmenu.py`
  (`CARD_BG_PROMPT`) and `art/README.md`.

## Fonts

The menu texts in `art/ui/` were rendered with the Georgia and Verdana fonts (Microsoft). Only the rendered pixels
are included, no font files.
