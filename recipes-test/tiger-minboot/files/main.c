/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Tiger contributors
 */
typedef unsigned int u32;
typedef unsigned long u64;
#define UART_BASE 0x09000000UL
#define REG(off) (*(volatile u32 *)(UART_BASE + (off)))
#define DATA_INITIAL 0x1122334455667788UL
#define DATA_POISON 0xdadadadadadadadaUL
#define BSS_POISON 0xb0b0b0b0b0b0b0b0UL
#ifndef TIGER_BUILD_ID
#error "Supply a source-derived TIGER_BUILD_ID"
#endif
volatile u64 test_data = DATA_INITIAL;
volatile u64 test_bss;
volatile u64 observed_el, observed_sp, observed_mpidr, observed_sctlr;

static void putc(char c)
{
    while (REG(0x18) & (1U << 5)) { }
    REG(0) = (u32)c;
}
static void puts(const char *s)
{
    while (*s) { putc(*s++); }
}
void firmware_main(void)
{
    u64 el, sp, mpidr, sctlr;
    u32 readonly;
    int init_ok = test_data == DATA_INITIAL && test_bss == 0;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    __asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
    __asm__ volatile("mrs %0, sctlr_el3" : "=r"(sctlr));
    /* Guest store, not a debugger write (debuggers can bypass ROM protection). */
    __asm__ volatile(
        "mov x9, xzr\n"
        "ldr w10, [x9]\n"
        "mvn w11, w10\n"
        "str w11, [x9]\n"
        "dsb sy\n"
        "ldr w12, [x9]\n"
        "cmp w10, w12\n"
        "cset %w0, eq\n"
        : "=r"(readonly) : : "x9", "x10", "x11", "x12", "cc", "memory");
    REG(0x30) = 0;
    REG(0x38) = 0;
    REG(0x44) = 0x7ff;
    REG(0x24) = 13;
    REG(0x28) = 1;
    REG(0x2c) = 0x60;  /* 8N1, FIFO disabled */
    REG(0x30) = 0x101; /* UARTEN | TXE */
    observed_el = el;
    observed_sp = sp;
    observed_mpidr = mpidr;
    observed_sctlr = sctlr;
    if (!init_ok || el != 12 || (mpidr & 0xffffffUL) != 0 ||
        (sp & 15) || sp < 0x40010000UL || sp > 0x40020000UL ||
        (sctlr & ((1UL << 0) | (1UL << 2) | (1UL << 12))) ||
        !readonly || REG(0x24) != 13 || REG(0x28) != 1 ||
        REG(0x2c) != 0x60 || REG(0x30) != 0x101 || REG(0x38) != 0) {
        puts("TIGER-CH4 FAIL\n");
    } else {
        /* State must be poisoned before the complete success line is visible. */
        test_data = DATA_POISON;
        test_bss = BSS_POISON;
        __asm__ volatile("dsb sy" : : : "memory");
        puts("TIGER-CH4 FW=" TIGER_BUILD_ID
             " CPU0 EL3 INIT=OK UART0 CFG=OK ROM=RO\n");
    }
    for (;;) { __asm__ volatile("wfe"); }
}
