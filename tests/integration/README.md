# T-016 formal Yocto integration

The layer pins the appended QEMU recipe to 8.2.7. Its 31 existing OE
patches remain first; the tiger patch is appended. conf/machine/tiger.conf
is only the chapter 4 freestanding test machine, not a Linux BSP.
It builds the AArch64 system target and removes native SDL, OpenGL/virgl
and KVM options: the experiment needs TCG and a serial backend. This
also avoids unrelated Mesa/LLVM compilation in a fresh build.

The fixture recipe uses the declared cross compiler, validates the ELF,
map and raw layout, generates config_bsp metadata with tracked inputs,
and publishes versioned assets through deploy.bbclass. Its generator
depends on qemu-helper-native:do_addto_recipe_sysroot. Relative staging
paths are calculated against the final deployment directory. The native
identity JSON binds validation to the generating build tree; regenerate
assets after moving a build tree rather than claiming it is relocatable.

## Clean reconstruction used for this stage

The validation uses /home/oops/workspace/build-t016-yocto with a fresh
TMPDIR and no workspace layer. Downloads remain in the original build
download directory. Other dependency sstate may be reused; these recipes
use an initially empty private SSTATE_DIR and no sstate mirrors:

    SSTATE_DIR:pn-qemu-system-native = "${TOPDIR}/sstate-t016-critical"
    SSTATE_DIR:pn-qemu-helper-native = "${TOPDIR}/sstate-t016-critical"
    SSTATE_DIR:pn-tiger-minboot = "${TOPDIR}/sstate-t016-critical"

Use MACHINE = "tiger". Record actual variables, task graph and task logs.
A successful cache lookup alone does not prove a clean reconstruction.

Before removing the original override, back up the workspace append,
MD5 registry and build configuration. The retained source is outside
the workspace at /home/oops/workspace/sources/qemu-system-native.
After checking the locked devtool implementation, this stage uses:

    devtool reset -n qemu-system-native

Do not pass --remove-work/-r. Preserve that directory, Git refs, retention
tag and bundle, and compare their identities before and after reset.
Do not delete the compatibility symlink or unrelated work/downloads.

## Build and validate

From the matching Poky environment:

    bitbake-layers show-appends
    bitbake -e qemu-system-native
    bitbake -e tiger-minboot
    bitbake -g tiger-minboot
    bitbake tiger-minboot

Pass the actual deployed versioned qemuboot config to runqemu with
nographic nonetwork. Never pass the raw .bin as a positional kernel.
The scripts below require unused output directories:

    python3 tests/integration/test-runqemu.py --runqemu <locked-poky>/scripts/runqemu --conf <deployed-conf> --out <new-evidence-directory>
    python3 tests/integration/test-deployment.py --runqemu <locked-poky>/scripts/runqemu --conf <deployed-conf> --out <another-new-directory>

The first script starts real runqemu, then verifies /proc executable
identity and final parameters, CPU/EL/UART reset state, guest startup
initialization, ROM contents, and two same-process host resets. It uses
QMP/GDB and instruction/PL011 traces, with the model stage's shared QMP
helper. QMP quit is the controlled successful termination. Instrumentation
starts paused but requires actual guest execution and three markers.

The deployment tests create private bad configs while preserving all
public deploy assets. They isolate missing BIOS/kernel inputs from the
launcher fallback glob, then verify an explicitly supplied kernel is
refused without guest instructions. The locked launcher logs that QEMU
error but returns zero: inspect its error and execution evidence rather
than treating that zero as boot success. Repeat the successful runqemu
test afterwards.
The model stage's tests/model/test-tiger.py must also be repeated using
the new helper binary and an alias view of the formally deployed
raw/ELF/manifest. Keep binary artifacts in the build workspace, and raw
text/JSON evidence in OPC. Design approval and author model tests do not
replace this formal integration/system validation.
