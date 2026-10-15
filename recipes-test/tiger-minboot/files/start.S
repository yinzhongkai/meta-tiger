/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Tiger contributors
 */
.section .text.start, "ax"
.global _start
.type _start, %function
_start:
    msr daifset, #0xf
    ldr x0, =__stack_top
    mov sp, x0
    ldr x0, =__data_load
    ldr x1, =__data_start
    ldr x2, =__data_end
1:  cmp x1, x2
    b.hs 2f
    ldr x3, [x0], #8
    str x3, [x1], #8
    b 1b
2:  ldr x1, =__bss_start
    ldr x2, =__bss_end
3:  cmp x1, x2
    b.hs 4f
    str xzr, [x1], #8
    b 3b
4:  bl firmware_main
5:  wfe
    b 5b
.size _start, . - _start
.section .note.GNU-stack, "", %progbits
