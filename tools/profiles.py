"""Version profiles: every game-specific address the build needs, found automatically by code patterns.

Works for any language version of GS1 / TLA that shares the code structure (verified: USA and Germany).
`profile_gs1(rom)` / `profile_tla(rom)` return dicts; `check_us()` asserts the values that were verified by hand
for the USA ROMs, so a broken pattern is noticed immediately.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsfs import Rom
from mapcode_calls import normalise_bls, map_code_indices
import gstext
import m4a
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
MC = 0x02008000                      # map code load address
ROM = 0x08000000
STUB = bytes.fromhex("004c2047")    # ldr r4,[pc,#0]; bx r4


def _insns(code, base=MC):
    """Linear Thumb disassembly that steps over lone BL halves (`mov lr, rX` + 0xF800 call idiom)."""
    out, pc = [], base
    end = base + len(code)
    while pc < end - 1:
        o = pc - base
        h = code[o] | (code[o + 1] << 8)
        if h & 0xF800 == 0xF800 and not (o >= 2 and (code[o - 2] | (code[o - 1] << 8)) & 0xF800 == 0xF000):
            out.append((pc, "blxlr", "")); pc += 2; continue
        ins = next(MD.disasm(code[o:o + 4], pc), None)
        if ins is None:
            out.append((pc, ".short", f"{h:#x}")); pc += 2; continue
        out.append((ins.address, ins.mnemonic, ins.op_str)); pc += ins.size
    return out


def _lit(code, ins_addr, op_str, base=MC):
    la = ((ins_addr + 4) & ~3) + int(op_str.split("#")[-1].rstrip("]"), 16)
    return struct.unpack_from("<I", code, la - base)[0]


def _bl_target(op_str):
    return int(op_str.lstrip("#"), 16)


def _find(seq, pred_list, start=0):
    """Index of the first position where consecutive instructions satisfy the given predicates."""
    for k in range(start, len(seq) - len(pred_list) + 1):
        if all(p(seq[k + j]) for j, p in enumerate(pred_list)):
            return k
    raise LookupError("pattern not found")


def is_(mn, ops=None, prefix=None):
    def p(i):
        if i[1] != mn:
            return False
        if ops is not None and i[2] != ops:
            return False
        if prefix is not None and not i[2].startswith(prefix):
            return False
        return True
    return p


ANY = lambda i: True


# ------------------------------------------------------------------------------------------------- GS1 --
def profile_gs1(path):
    g = Rom(path)
    d = g.data
    p = {"code": g.code, "path": path, "mft_off": g.mft_off, "code_end": g.mft_off}
    mcs = map_code_indices(g)
    p["mapcode"] = (mcs[0], mcs[-1] + 1)
    p["text_table"] = gstext.find_text_table(d, 0, g.mft_off)
    p["song_table"] = _find_song_table(d, g.mft_off)

    # title map code (map 1): "after the credits" branch and the clear-data save it calls
    title_idx = struct.unpack_from("<H", d, _map_table(d, g.mft_off, mcs[0]) + 8)[0]
    p["title_mapcode"] = title_idx
    code = normalise_bls(g.decompressed(title_idx))
    seq = _insns(code)
    k = _find(seq, [is_("ldr", prefix="r3, [pc"), is_("movs", "r0, #0xe1"), is_("lsls", "r0, r0, #1"),
                    is_("adds", "r3, r3, r0"), is_("movs", "r1, #0"), is_("ldrsh"), is_("cmp", "r3, #2"),
                    is_("bne")])
    p["cleared_branch"] = seq[k + 8][0]
    assert _lit(code, seq[k][0], seq[k][2]) == 0x02000240
    # marker: ldr r3,=0x02000240; ldr r2,=OFF; adds r3,r3,r2; movs r2,#1; strb r2,[r3]; bl SAVE
    m = _find(seq, [is_("ldr", prefix="r3, [pc"), is_("ldr", prefix="r2, [pc"), is_("adds", "r3, r3, r2"),
                    is_("movs", "r2, #1"), is_("strb", "r2, [r3]"), is_("bl")], k)
    p["clear_marker"] = _lit(code, seq[m][0], seq[m][2]) + _lit(code, seq[m + 1][0], seq[m + 1][2]) - 0x02000000
    thunk = _bl_target(seq[m + 5][2])
    stub = struct.unpack_from("<I", code, thunk + 4 - MC)[0]          # map-code thunk -> engine stub
    fn = struct.unpack_from("<I", d, (stub & ~1) - ROM + 4)[0] if d[(stub & ~1) - ROM:(stub & ~1) - ROM + 4] == STUB else stub
    p["save_clear_fn"] = fn & ~1
    p.update(_gs1_save_calls(d, fn & ~1))
    p["encounter_returns"] = _encounter_returns(g)
    p.update(_m4a(d, p["song_table"], g.mft_off))
    p.update(_iwram_image(d))
    return p


def _m4a(d, song_table, end):
    """GS1's MusicPlayer2000 (m4a) entry points, used by the start screen to play GS1's intro music.

    m4aSongNumStart = first function whose literal pool holds the song table (push {lr}; lsls r0,r0,#16 ...),
    m4aSoundMain = the 4-instruction wrapper right before it, m4aSoundInit = the push {r4-r6,lr} function before
    that, m4aSoundVSync by its body (SOUND_INFO_PTR, ident 'Smsh', pcmDmaCounter at +4)."""
    import re
    lit = struct.pack("<I", ROM + song_table)
    o = d.find(lit)
    while True:                                   # first song-table literal that belongs to m4aSongNumStart
        start = d.rfind(bytes.fromhex("00b50004"), o - 0x40, o) if o % 4 == 0 else -1
        main = start - 0xC
        if start > 0 and d[main:main + 2] == bytes.fromhex("00b5") and                 d[main + 6:main + 10] == bytes.fromhex("01bc0047"):      # push {lr}; bl; pop {r0}; bx r0
            break
        o = d.find(lit, o + 1)
        assert o >= 0, "m4aSongNumStart"
    init = d.rfind(bytes.fromhex("70b5"), main - 0x100, main)                   # push {r4, r5, r6, lr}
    # ldr r0,=SOUND_INFO_PTR; ldr r0,[r0]; ldr r2,='Smsh'; ldr r3,[r0]; subs r3,r3,r2; cmp r3,#1; bhi; ldrb r1,[r0,#4]
    hdr = struct.unpack_from("<I", d, song_table + 8 * INTRO_SONG)[0] - ROM
    assert d[hdr] == 7, "intro song: unexpected track count"
    x = lambda h: re.escape(bytes.fromhex(h))
    m = re.search(b"." + x("480068") + b"." + x("4a03689b1a012b") + b"." + x("d80179"), d[:end], re.DOTALL)
    return {"m4a_song_start": ROM + start, "m4a_main": ROM + main, "m4a_init": ROM + init,
            "m4a_vsync": ROM + m.start(), "intro_song": INTRO_SONG}


INTRO_SONG = 70             # GS1 intro / title music; same number in USA and German ROMs (checked by note data)
INTRO_SONG_LEAD = 9         # the song starts 9 frames before the intro picture fades in


def _iwram_image(d):
    """GS1 copies code (IRQ handler, division helpers used by the sound engine, ...) to IWRAM at start-up:
    crt0 -> main (literal after the ROM entry) -> 2nd call = setup: DMA3 from SRC to 0x03000000 with CTRL.
    Returns {"iwram_src": ROM address, "iwram_bytes": length} so the start screen can do the same copy."""
    entry = 8 + ((struct.unpack_from("<I", d, 0)[0] & 0xFFFFFF) << 2)
    main = next(w & ~1 for w in struct.unpack_from("<32I", d, entry)
                if ROM <= w < ROM + 0x10000 and w & 1)                     # ldr r1,=main|1; bx r1
    seq = _insns(d[main - ROM:main - ROM + 0x100], main)
    calls = [i for i in seq if i[1] == "bl"]
    setup = _bl_target(calls[1][2])
    code = d[setup - ROM:setup - ROM + 0x80]
    s2 = _insns(code, setup)
    k = _find(s2, [is_("ldr", prefix="r4, [pc"), is_("ldr", prefix="r3, [pc"), is_("ldr", prefix="r0, [pc"),
                   is_("adds", "r1, r4, #0"), is_("ldr", prefix="r2, [pc")])
    assert _lit(code, s2[k][0], s2[k][2], setup) == 0x03000000
    src = _lit(code, s2[k + 2][0], s2[k + 2][2], setup)
    ctrl = _lit(code, s2[k + 4][0], s2[k + 4][2], setup)
    assert ctrl >> 24 == 0x84, "32-bit DMA expected"
    return {"iwram_src": src, "iwram_bytes": (ctrl & 0xFFFF) * 4}


def _encounter_returns(g):
    """Return addresses after the two calls of GS1's "check encounter" routine (tests force battles there).

    Wrapper A: ...; ldrb r0,[r3,r0]; bl ENC; pop {r1}     Wrapper B: push {r5,lr}; adds r5,r1,#0; bl X;
    adds r1,r5,#0; bl ENC; pop {r5}. Both live in engine file 6."""
    d = g.data
    lo, hi = g.file_span(6)[0], g.file_span(6)[0] + 0x20000
    seq = _insns(d[lo:hi], ROM + lo)
    a = _find(seq, [is_("adds", "r3, r3, r2"), is_("ldrb", "r0, [r3, r0]"), is_("bl"), is_("pop", "{r1}")])
    enc = _bl_target(seq[a + 2][2])
    b = _find(seq, [is_("adds", "r1, r5, #0"), is_("bl"), is_("pop", "{r5}")])
    assert _bl_target(seq[b + 1][2]) == enc
    return (seq[a + 2][0] + 4, seq[b + 1][0] + 4)


def _map_table(d, mft_off, first_mapcode):
    """Map table: 8-byte entries {u16 mapcode, ...} starting with consecutive map code indices."""
    pat = struct.pack("<H", first_mapcode)
    for o in range(0, mft_off, 2):
        if d[o:o + 2] == pat and struct.unpack_from("<H", d, o + 8)[0] == first_mapcode + 1 \
                and struct.unpack_from("<H", d, o + 16)[0] == first_mapcode + 2:
            return o
    raise LookupError("map table")


def _find_song_table(d, end):
    size = len(d)
    best = None
    for o in range(0, end - 16, 4):
        n, x = 0, o
        while x + 8 <= size:
            w = struct.unpack_from("<I", d, x)[0]
            if ROM <= w < ROM + size and m4a._looks_like_header(d, w - ROM) and d[w - ROM] > 0:
                n += 1; x += 8
            else:
                break
        if n >= 20 and (best is None or n > best[1]):
            best = (o, n)
    return m4a.find_table_start(d, best[0])


def _gs1_save_calls(d, fn):
    """From GS1's clear-data save routine: flash scan, init, prepare, actor positions, WriteSlot."""
    code = d[fn - ROM:fn - ROM + 0x200]
    seq = _insns(code, fn)
    bls = [(a, _bl_target(o)) for a, m, o in seq if m == "bl"]
    # "bl PREPARE; bl ACTORS; ldr r5,=0x02000000; adds r0,r7,#0; adds r1,r5,#0; bl WRITESLOT"
    k = _find(seq, [is_("bl"), is_("bl"), is_("ldr", prefix="r5, [pc"), is_("adds", "r0, r7, #0"),
                    is_("adds", "r1, r5, #0"), is_("bl")])
    assert _lit(code, seq[k + 2][0], seq[k + 2][2], fn) == 0x02000000
    # "ldr r3,=SLOT_VAR; (other); strh r7,[r3]" (the chosen slot is stored before saving)
    sv = next(j for i, (a, m, o) in enumerate(seq) if m == "strh" and o.startswith("r7, [r3")
              for j in range(i - 1, i - 4, -1) if seq[j][1] == "ldr" and seq[j][2].startswith("r3, [pc"))
    return {
        "slot_var": _lit(code, seq[sv][0], seq[sv][2], fn),
        "fn_flash_scan": bls[0][1],
        "fn_save_init": _first_bl_after_branch(seq, bls),
        "fn_prepare": _bl_target(seq[k][2]),
        "fn_actors": _bl_target(seq[k + 1][2]),
        "fn_write_slot": _bl_target(seq[k + 5][2]),
    }


def _first_bl_after_branch(seq, bls):
    """`bl scan; adds r6,r0,#0; cmp r6,#0; beq OK; ...; OK: bl INIT` -> INIT."""
    k = _find(seq, [is_("cmp", "r6, #0"), is_("beq")])
    target = int(seq[k + 1][2].lstrip("#"), 16)
    for a, m, o in seq:
        if a >= target and m == "bl":
            return _bl_target(o)
    raise LookupError("save init")


# ------------------------------------------------------------------------------------------------- TLA --
def profile_tla(path):
    t = Rom(path)
    d = t.data
    p = {"code": t.code, "path": path, "mft_off": t.mft_off}
    p["entry"] = 0x08000000 + 8 + ((struct.unpack_from("<I", d, 0)[0] & 0xFFFFFF) << 2)
    mcs = map_code_indices(t)
    title_idx = struct.unpack_from("<H", d, _map_table(d, t.mft_off, mcs[0]) + 8)[0]
    p["title_mapcode"] = title_idx
    code = normalise_bls(t.decompressed(title_idx))
    seq = _insns(code)
    addr = {a: i for i, (a, m, o) in enumerate(seq)}

    # cable receive function: the only one loading SIOCNT (0x04000128)
    k = next(i for i, (a, m, o) in enumerate(seq) if m == "ldr" and "pc" in o and _lit(code, a, o) == 0x04000128)
    start = max(a for a, m, o in seq[:k] if m == "push" and "lr" in o)
    p["recv_fn"] = start
    p["recv_patch_at"] = start + 12
    assert code[start - MC:start - MC + 12] == bytes.fromhex("e0b557464e464546e0b481b0"), "receive prologue"
    s = _find(seq, [is_("ldr", prefix="r5, [pc"), is_("movs"), is_("ldr", prefix="r6, [pc"), is_("ldr", prefix="r1, [pc")],
              addr[start])
    assert _lit(code, seq[s][0], seq[s][2]) == 0x02000040
    p["recv_success"] = seq[s][0]
    p["recv_buffer"] = _lit(code, seq[s + 3][0], seq[s + 3][2]) - 0x40
    e = _find(seq, [is_("add", "sp, #4"), is_("pop", "{r3, r5, r6}")], s)
    p["recv_epilogue"] = seq[e][0]

    # new game: Link path = block that backs up RAM and calls the receive function, followed by the review call
    calls = [i for i, (a, m, o) in enumerate(seq) if m == "bl" and _bl_target(o) == start]
    for c in calls:
        if seq[c + 1][1:] == ("adds", "r7, r0, #0") and seq[c + 2][1:] == ("cmp", "r7, r8") and seq[c + 4][1] == "bl":
            break
    else:
        raise LookupError("new-game receive call")
    lp = next(i for i in range(c, c - 12, -1) if seq[i][1] == "ldr" and seq[i][2].startswith("r5, [pc")
              and _lit(code, seq[i][0], seq[i][2]) == 0x02000000)
    p["link_path"] = seq[lp][0]
    p["review_call"] = seq[c + 4][0]
    p["review_fn"] = _bl_target(seq[c + 4][2])

    a = _find(seq, [is_("ldr", prefix="r0, [pc"), is_("movs", "r1, #0xd"), is_("bl"), is_("movs", "r0, #1"),
                    is_("movs", "r1, #0"), is_("movs", "r2, #0"), is_("movs", "r3, #0"), is_("bl")])
    assert seq[a][0] < p["link_path"]
    p["ask_transfer"] = seq[a][0]
    p["ask_msg"] = _lit(code, seq[a][0], seq[a][2])

    tc = _find(seq, [is_("bl"), is_("adds", "r5, r0, #0"), is_("cmp", "r5, #0"), is_("bge")])
    p["title_call"] = seq[tc][0]
    p["title_fn"] = _bl_target(seq[tc][2])

    nl = _find(seq, [is_("movs", "r6, #0"), is_("movs", "r7, #1"), is_("movs", "r0, #6"), is_("bl"),
                     is_("adds", "r0, r6, #0"), is_("bl")])
    p["name_loop"] = seq[nl][0]
    p["name_loop_body"] = seq[nl + 2][0]
    done = _find(seq, [is_("adds", "r6, #1"), is_("cmp", "r6, r7"), is_("blt")], nl)
    p["name_loop_done"] = seq[done + 3][0]
    return p


# ------------------------------------------------------------------------------------------------ checks --
US_GS1 = {"mft_off": 0x320000, "title_mapcode": 880, "cleared_branch": 0x02008416, "clear_marker": 0x44F,
          "fn_flash_scan": 0x080056CC, "fn_save_init": 0x08005C68, "fn_prepare": 0x0801F818,
          "fn_actors": 0x0808A5B0, "fn_write_slot": 0x08005920, "song_table": 0x0FC684, "slot_var": 0x02002004,
          "encounter_returns": (0x0808B03E, 0x0808B056)}
US_TLA = {"entry": 0x08000428, "title_mapcode": 1610, "recv_patch_at": 0x02008B30, "recv_success": 0x02008D0E,
          "recv_epilogue": 0x02008D6E, "recv_buffer": 0x02013000, "link_path": 0x020084EA,
          "review_call": 0x02008504, "review_fn": 0x0200A3E8, "ask_transfer": 0x020084B6,
          "title_call": 0x020083F4, "title_fn": 0x0200A2F0, "name_loop": 0x02008574,
          "name_loop_body": 0x02008578, "name_loop_done": 0x020085A8}


def check_us(gs1_path, tla_path):
    g, t = profile_gs1(gs1_path), profile_tla(tla_path)
    for want, got, tag in ((US_GS1, g, "GS1"), (US_TLA, t, "TLA")):
        for k, v in want.items():
            assert got[k] == v, f"{tag} {k}: found {got[k]}, expected {v}"
    return g, t


if __name__ == "__main__":
    for path in sys.argv[1:]:
        r = Rom(path)
        prof = profile_gs1(path) if r.code.startswith("AGS") else profile_tla(path)
        print(r.code)
        for k, v in prof.items():
            print(f"  {k:18s} {hex(v) if isinstance(v, int) else v}")


def find_flash_ids(d):
    """Offsets of the AgbFlash chip-ID halfwords for Macronix (0x1CC2) and Panasonic (0x1B32).

    Each chip entry ends with {totalSize=0x10000, sector info..., ids}; ids sit 0x14 bytes after totalSize."""
    s = d.find(b"FLASH_V")
    assert s >= 0, "AgbFlash marker"
    out = {}
    for ident in (0x1CC2, 0x1B32):
        for o in range(s - 0x200, s + 0x600, 2):
            if struct.unpack_from("<H", d, o)[0] == ident and struct.unpack_from("<I", d, o - 0x14)[0] == 0x10000:
                out[ident] = o
                break
        else:
            raise LookupError(f"flash id {ident:#x}")
    return s, out
