/* Cartridge runtime: code and read-only data in ROM at RUNTIME_BASE; no writable sections allowed. */
ENTRY(tla_receive_gs1)
SECTIONS
{
    . = 0x09B00000;
    .text : { *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.comment) *(.ARM.attributes) *(.note*) }
    ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "runtime must not use RAM sections")
}
