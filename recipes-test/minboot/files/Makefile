# SPDX-License-Identifier: MIT
CROSS_COMPILE ?= aarch64-poky-linux-
OUT ?= build
CC = $(CROSS_COMPILE)gcc
OBJCOPY = $(CROSS_COMPILE)objcopy

FLAGS := -O2 -Wall -Wextra -Werror -march=armv8-a -mgeneral-regs-only -mstrict-align -ffreestanding
FLAGS += -fno-builtin -fno-stack-protector -fno-pie -fno-pic -fno-unwind-tables -fno-asynchronous-unwind-tables
FLAGS += -nostdlib -nostartfiles -static -no-pie

.PHONY: all
all:
	mkdir -p "$(OUT)"
	$(CC) $(FLAGS) start.S main.c -Wl,--build-id=none,-T,minboot.ld "-Wl,-Map,$(OUT)/minboot.map" -o "$(OUT)/minboot.elf"
	$(OBJCOPY) -O binary "$(OUT)/minboot.elf" "$(OUT)/minboot.bin"
