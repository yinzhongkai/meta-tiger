SUMMARY = "Freestanding chapter 4 tiger CPU/UART/reset test fixture"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://COPYING.MIT;md5=c40e692aecd2602002ed2d1007a82647"

SRC_URI = "file://start.S file://main.c file://tiger-minboot.ld \
           file://COPYING.MIT file://build-fixture.py"
S = "${WORKDIR}"
B = "${WORKDIR}/build"
COMPATIBLE_MACHINE = "^tiger$"
PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = ""
INHIBIT_DEFAULT_DEPS = "1"
DEPENDS = "virtual/${TARGET_PREFIX}gcc virtual/${TARGET_PREFIX}binutils"
inherit deploy python3native

TIGER_SOURCE_REV = "b303ae6d614f067e11d4cbba57feacaf84ee7e8e"
TIGER_ASSET = "tiger-minboot-${PV}-${MACHINE}"
TIGER_FIXTURE_FLAGS = "-O2 -Wall -Wextra -Werror -march=armv8-a \
    -mgeneral-regs-only -mstrict-align -ffreestanding -fno-builtin \
    -fno-stack-protector -fno-pie -fno-pic -fno-unwind-tables \
    -fno-asynchronous-unwind-tables -nostdlib -nostartfiles -static -no-pie"

do_configure[noexec] = "1"
do_install[noexec] = "1"

do_compile() {
    ${PYTHON} ${S}/build-fixture.py --src=${S} --out=${B} \
        --cc="${CC}" --objcopy="${OBJCOPY}" --readelf="${READELF}" \
        --nm="${NM}" --objdump="${OBJDUMP}" --flags="${TIGER_FIXTURE_FLAGS}" \
        --source-revision="${TIGER_SOURCE_REV}"
}

def tiger_qb_vars(d):
    return [k for k in d.keys() if k.startswith('QB_')] + \
        ['MACHINE', 'TUNE_ARCH', 'DEPLOY_DIR_IMAGE', 'BASE_WORKDIR', 'BUILD_SYS',
         'RECIPE_SYSROOT', 'TIGER_ASSET', 'SERIAL_CONSOLES']

do_generate_qemuboot[depends] += "qemu-helper-native:do_addto_recipe_sysroot"
do_generate_qemuboot[vardeps] += "${@' '.join(tiger_qb_vars(d))}"
python do_generate_qemuboot() {
    import configparser
    import json
    import os
    import hashlib

    finaldir = d.getVar('DEPLOY_DIR_IMAGE')
    helper = os.path.join(d.getVar('BASE_WORKDIR'), d.getVar('BUILD_SYS'),
                          'qemu-helper-native/1.0/recipe-sysroot-native')
    roots = {'STAGING_DIR_NATIVE': helper,
             'STAGING_BINDIR_NATIVE': os.path.join(helper, 'usr/bin'),
             'STAGING_DIR_HOST': d.getVar('RECIPE_SYSROOT')}
    conf = configparser.ConfigParser(interpolation=None)
    conf.add_section('config_bsp')
    for key in sorted(set(tiger_qb_vars(d))):
        if key.startswith('QB_') or key in ('MACHINE', 'TUNE_ARCH', 'SERIAL_CONSOLES'):
            conf.set('config_bsp', key, d.getVar(key) or '')
    for key, path in roots.items():
        if not os.path.isdir(path):
            bb.fatal('Missing staging path: %s=%s' % (key, path))
        relative = os.path.relpath(path, finaldir)
        if relative != '.' and not relative.startswith('../'):
            bb.fatal('runqemu cannot expand staging path: %s' % relative)
        conf.set('config_bsp', key, relative)
    binary = os.path.join(helper, 'usr/bin', d.getVar('QB_SYSTEM_NAME'))
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        bb.fatal('Missing helper system emulator: %s' % binary)
    conf.set('config_bsp', 'DEPLOY_DIR_IMAGE', '.')
    conf.set('config_bsp', 'QB_DEFAULT_BIOS', d.getVar('TIGER_ASSET') + '.bin')
    output = os.path.join(d.getVar('B'), d.getVar('TIGER_ASSET') + '.qemuboot.conf')
    with open(output, 'w') as stream:
        conf.write(stream)
    identity = {'qemu_path': binary,
                'qemu_sha256': hashlib.sha256(open(binary, 'rb').read()).hexdigest(),
                'paths': roots,
                'configuration_sha256': hashlib.sha256(open(output, 'rb').read()).hexdigest()}
    with open(os.path.join(d.getVar('B'), 'native-identity.json'), 'w') as stream:
        json.dump(identity, stream, indent=2)
        stream.write('\n')
}
addtask generate_qemuboot after do_compile before do_deploy

do_deploy() {
    install -d ${DEPLOYDIR}
    for suffix in bin elf map; do
        install -m 0644 ${B}/tiger-minboot.$suffix ${DEPLOYDIR}/${TIGER_ASSET}.$suffix
    done
    for name in manifest.json readelf.txt nm.txt disassembly.txt commands.json native-identity.json; do
        install -m 0644 ${B}/$name ${DEPLOYDIR}/${TIGER_ASSET}-$name
    done
    install -m 0644 ${B}/${TIGER_ASSET}.qemuboot.conf ${DEPLOYDIR}/
}
addtask deploy after do_generate_qemuboot before do_build
