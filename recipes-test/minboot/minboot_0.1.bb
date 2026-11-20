SUMMARY = "Bare-metal UART firmware for the tiger machine"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://COPYING.MIT;md5=c40e692aecd2602002ed2d1007a82647"

SRC_URI = " \
    file://start.S \
    file://main.c \
    file://minboot.ld \
    file://COPYING.MIT \
    file://Makefile \
"
S = "${WORKDIR}"
B = "${WORKDIR}/build"
COMPATIBLE_MACHINE = "^tiger$"
PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = ""
INHIBIT_DEFAULT_DEPS = "1"
DEPENDS = "virtual/${TARGET_PREFIX}gcc virtual/${TARGET_PREFIX}binutils"
inherit deploy

TIGER_ASSET = "minboot-${PV}-${MACHINE}"
do_configure[noexec] = "1"
do_install[noexec] = "1"

do_compile() {
    oe_runmake -C "${S}" OUT="${B}" CC="${CC}" OBJCOPY="${OBJCOPY}"
}

do_deploy() {
    install -d ${DEPLOYDIR}
    for suffix in bin elf map; do
        install -m 0644 ${B}/minboot.$suffix ${DEPLOYDIR}/${TIGER_ASSET}.$suffix
    done
}
addtask deploy after do_compile before do_build
