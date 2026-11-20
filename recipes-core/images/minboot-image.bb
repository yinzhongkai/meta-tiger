# SPDX-License-Identifier: MIT
SUMMARY = "QEMU startup configuration for the tiger bare-metal firmware"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${WORKDIR}"
COMPATIBLE_MACHINE = "^tiger$"
PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = ""
INHIBIT_DEFAULT_DEPS = "1"

inherit deploy qemuboot

IMAGE_NAME = "${PN}-${MACHINE}"
IMAGE_LINK_NAME = ""
IMGDEPLOYDIR = "${B}/qemuboot"

do_build[depends] += "minboot:do_deploy qemu-helper-native:do_addto_recipe_sysroot"

do_deploy() {
    install -D -m 0644 "${IMGDEPLOYDIR}/${IMAGE_NAME}.qemuboot.conf" "${DEPLOYDIR}/${IMAGE_NAME}.qemuboot.conf"
}
addtask deploy after do_write_qemuboot_conf before do_build
