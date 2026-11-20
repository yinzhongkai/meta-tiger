/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Tiger contributors
 */
typedef unsigned int u32;

#define UART_BASE 0x09000000UL
#define REG(off) (*(volatile u32 *)(UART_BASE + (off)))

static void uart_putc(char c)
{
    while (REG(0x18) & (1U << 5)) {
    }
    REG(0) = (u32)c;
}

static void uart_puts(const char *s)
{
    while (*s) {
        uart_putc(*s++);
    }
}

int main(void)
{
    REG(0x30) = 0;
    REG(0x38) = 0;
    REG(0x44) = 0x7ff;
    REG(0x24) = 13;
    REG(0x28) = 1;
    REG(0x2c) = 0x60;  /* 8N1, FIFO disabled */
    REG(0x30) = 0x101; /* UARTEN | TXE */

    uart_puts("TIGER-CH4: Hello from UART0!\n");
    return 0;
}
