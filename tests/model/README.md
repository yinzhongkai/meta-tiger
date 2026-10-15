# T-016 model-stage handoff

This package implements the A-005 v0.2 minimum: TCG, one AArch64
Cortex-A53, a 1 MiB ROM at zero, 1 GiB RAM at 0x40000000, and a polling
PL011 at 0x09000000. The UART has a 24 MHz clock input. CPU cntfrq is set
explicitly. There is no GIC or UART IRQ connection in this stage.

The QEMU patch is GPL-2.0-or-later. The firmware and Python model tools
are MIT licensed; see recipes-test/tiger-minboot/files/COPYING.MIT.

## Source and development baseline

The source package is qemu-8.2.7.tar.xz, SHA-256
1f0604f296ab9acb4854c054764a1ba408643fc299bd54a6500cccfaaca65b55.
Poky is 77d1feb37e280733684ae8a9449fb031d5d7ff40.
The existing recipe applies 29 common and two class-native patches.

This run used:

    source /home/oops/workspace/poky/oe-init-build-env /home/oops/workspace/build
    bitbake -e qemu-system-native
    devtool status
    devtool modify qemu-system-native
    devtool build qemu-system-native

The temporary source is build/workspace/sources/qemu-system-native.
Its patched development base is
3a261f929a6154bdc315aabf4cb6c79c57f73652 (31 commits after devtool-base
041c1c65762b96bce77da424335150d654bf144a). These are this extraction's
temporary Git IDs; repeat extractions can have different import IDs.
Verify package/patch content and the selected native override as well.

In this devtool environment, B changed to:

    /home/oops/workspace/build/tmp/work/x86_64-linux/qemu-system-native/8.2.7/qemu-8.2.7

Its config-host.mak points SRC_PATH at the workspace source. The older
sibling build/ directory can contain a different QEMU. Check actual B,
SRC_PATH, executable hash and machine registration before executing.
Do not infer the new binary from a previously observed directory.

Apply the single patch in recipes-devtools/qemu/files/ after the 31 OE
patches. It adds hw/arm/tiger.c and updates hw/arm/{Kconfig,meson.build}.
The ROM initialization uses a NULL migration owner: QEMU 8.2.7
memory_region_init_rom accepts NULL or DeviceState, not MachineState.
The region storage and arm_boot_info live in the machine for its entire
lifetime. arm_load_kernel is called once; it registers the CPU reset
handler. Repeated resets do not reconstruct objects or call it again.

## Firmware and standalone build

The source is recipes-test/tiger-minboot/files/{start.S,main.c,tiger-minboot.ld}.
_start is at zero. Startup establishes SP_EL3=0x40020000, copies data
from its ROM LMA into RAM, and clears BSS. The link script asserts the
ROM and data/BSS limits. Compilation disables implicit runtime support,
PIE, stack protection and SIMD register use.

For the existing toolchain used by this model run:

    python3 tests/model/build-minboot.py \
      --cc /home/oops/workspace/build/tmp/work/cortexa57-poky-linux/libedit/20230828-3.1/recipe-sysroot-native/usr/bin/aarch64-poky-linux/aarch64-poky-linux-gcc \
      --out /home/oops/workspace/build/t016-qemu/fixture-new

Use a fresh output directory. The manifest records source hashes, flags,
compiler identity, ELF/map/raw hashes and symbols. The guest build ID
hashes named source contents plus flags; it does not embed the raw hash.
The formal target recipe can reproduce these assumptions using its own
declared compiler and metadata.

UART setup uses aligned 32-bit MMIO, IMSC=0, ICR=0x7ff, IBRD=13, FBRD=1,
LCR_H=0x60 and CR=0x101. Register readback is checked separately from
character output; PL011's DR path alone does not enforce TX enable or
prove baud timing. The guest checks CurrentEL, MPIDR, SP alignment/range
and MMU/cache state, probes ROM with a guest store, and poisons data/BSS
before printing its complete success line.

## Model tests and evidence

    python3 tests/model/test-tiger.py \
      --qemu /home/oops/workspace/build/tmp/work/x86_64-linux/qemu-system-native/8.2.7/qemu-8.2.7/qemu-system-aarch64 \
      --fixture /home/oops/workspace/build/t016-qemu/fixture-new \
      --out /home/oops/workspace/build/t016-qemu/model-new

The runner saves its source snapshot, full argv, QMP traffic, GDB
commands/output, instruction/UART traces, state snapshots, raw outputs
and return codes. It requires an unused output directory.

Cold execution and two warm resets run in the same QEMU process.
Before each continuation, PC/EL and UART reset values are inspected.
GDB then breaks at firmware_main to inspect actual startup data/BSS/SP.
After the guest completes its line, the runner verifies changed
sentinels, CPU state, UART readback and a full ROM snapshot. A reset
must retain RAM sentinels until startup reinitializes them; the second
and third lines must come from the guest again. RESET events are awaited
before reading state. Successful processes exit through QMP quit.

The exactly-1-MiB image is a padded valid fixture. It tests the length
boundary and actual execution of that particular content; arbitrary
legal-length images are not guaranteed to boot. Expected rejection
requires exit code 1, the corresponding diagnostic and no instruction
or guest output. A crash is a failure.

Formal bbappend/SRC_URI integration, MACHINE=tiger configuration, fixture
deploy/qemuboot generation, helper sysroot, workspace reset, clean
BitBake reconstruction and runqemu verification are the next Yocto
stage. The current development build still uses MACHINE=qemuarm64.
Preserve this workspace until the handoff is accepted and the final
increment has been integrated; devtool reset and cleanup follow that
stage's recorded plan. Model results do not constitute system acceptance.
