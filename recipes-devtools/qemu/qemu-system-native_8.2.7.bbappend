# SPDX-License-Identifier: MIT
# Apply only to the system emulator used by runqemu; retain the OE patch list.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI:append = " file://0001-arm-add-minimal-tiger-machine.patch"
