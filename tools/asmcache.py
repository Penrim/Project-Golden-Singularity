"""Assembler with a cache, so players can build without keystone.

Every snippet the build assembles (boot stub, title-code hooks) depends only on the source text and its address,
which are fixed for each supported ROM version pair. Developers (keystone installed) fill data/asm_cache.json during
a normal build; players read from it. A snippet that is not in the cache needs keystone (BUILDING.md, Developers).
"""
import hashlib, json, os

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "asm_cache.json")
_cache = None


def _load():
    global _cache
    if _cache is None:
        _cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    return _cache


def assemble(mode, src, base):
    """mode "arm" or "thumb"; returns bytes."""
    key = hashlib.sha1(f"{mode}|{base:#x}|{src}".encode()).hexdigest()
    c = _load()
    if key in c:
        return bytes.fromhex(c[key])
    try:
        from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM, KS_MODE_THUMB
    except ImportError:
        raise SystemExit("this build needs code that is not in data/asm_cache.json; install keystone-engine "
                         "(see BUILDING.md, Developers)")
    code, _ = Ks(KS_ARCH_ARM, KS_MODE_ARM if mode == "arm" else KS_MODE_THUMB).asm(src, base)
    c[key] = bytes(code).hex()
    json.dump(c, open(CACHE, "w"), indent=0, sort_keys=True)
    return bytes(code)
