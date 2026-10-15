/* SPDX-License-Identifier: MIT */
ENTRY(_start)
MEMORY {
    ROM (rx) : ORIGIN = 0, LENGTH = 1M
    DATA (rw) : ORIGIN = 0x40000000, LENGTH = 64K
}
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) . = ALIGN(8); } > ROM
    .data : { __data_start = .; *(.data*) . = ALIGN(8); __data_end = .; }
        > DATA AT> ROM
    __data_load = LOADADDR(.data);
    .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON)
                     . = ALIGN(8); __bss_end = .; } > DATA
    __stack_bottom = 0x40010000;
    __stack_top = 0x40020000;
    /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
ASSERT(_start == 0, "firmware entry must be zero")
ASSERT(__data_load + SIZEOF(.data) <= 0x100000, "ROM overflow")
ASSERT(__bss_end <= 0x40010000, "data/BSS overflow")
ASSERT((__stack_top & 15) == 0, "stack must be 16-byte aligned")
