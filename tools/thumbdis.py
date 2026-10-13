"""Thumb disassembly helpers for ROM code and map code blobs (literal pools resolved)."""
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def dis(blob, base, addr, n=60, stop_at_return=True):
    """Disassemble `blob` (mapped at `base`) from `addr`. Returns lines with literal values resolved."""
    o = (addr & ~1) - base
    out, far = [], addr & ~1
    for ins in MD.disasm(blob[o:o + n * 2], addr & ~1):
        s = f"{ins.address:08x}  {ins.mnemonic:6s} {ins.op_str}"
        m, ops = ins.mnemonic, ins.op_str
        if m.startswith("ldr") and "pc" in ops:
            la = ((ins.address + 4) & ~3) + int(ops.split("#")[-1].rstrip("]"), 16)
            if 0 <= la - base < len(blob) - 3:
                s += f"    ; ={struct.unpack_from('<I', blob, la - base)[0]:#010x}"
        if m.startswith("b") and m not in ("bl", "bx", "blx", "bic", "bics") and ops.startswith("#"):
            far = max(far, int(ops[1:], 16))
        out.append(s)
        if stop_at_return and ins.address >= far and ((m == "pop" and "pc" in ops) or m == "bx"):
            break
    return out


def rom_dis(rom, addr, n=60, **kw):
    return dis(rom.data, 0x08000000, addr, n, **kw)
