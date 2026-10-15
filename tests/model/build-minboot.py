#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the standalone model fixture; formal BitBake deploy belongs to Yocto."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    src = Path(__file__).resolve().parents[2] / "recipes-test/tiger-minboot/files"
    cc = args.cc.absolute()
    prefix = str(cc)[:-3]
    tools = {k: prefix + k for k in ("objcopy", "readelf", "nm", "objdump")}
    commands = []

    def run(argv, file=None):
        print("COMMAND", json.dumps([str(a) for a in argv]), flush=True)
        p = subprocess.run([str(a) for a in argv], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        commands.append({"argv": [str(a) for a in argv], "rc": p.returncode,
                         "output": p.stdout})
        if file:
            (out / file).write_text(p.stdout)
        else:
            print(p.stdout, end="", flush=True)
        (out / "commands.json").write_text(json.dumps(commands, indent=2))
        if p.returncode:
            raise RuntimeError("command failed: " + str(argv))
        return p.stdout

    flags = ["-O2", "-Wall", "-Wextra", "-Werror", "-march=armv8-a",
             "-mgeneral-regs-only", "-mstrict-align", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-fno-pie", "-fno-pic",
             "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
             "-nostdlib", "-nostartfiles", "-static", "-no-pie"]
    inputs = ["start.S", "main.c", "tiger-minboot.ld", "COPYING.MIT"]
    h = hashlib.sha256()
    for name in inputs:
        h.update(name.encode() + b"\0" + (src / name).read_bytes() + b"\0")
    h.update(json.dumps(flags).encode())
    build_id = "sha256:" + h.hexdigest()
    elf, raw = out / "tiger-minboot.elf", out / "tiger-minboot.bin"
    version = run([cc, "--version"])
    run([cc, *flags, '-DTIGER_BUILD_ID="' + build_id + '"',
         src / "start.S", src / "main.c", "-Wl,--build-id=none",
         "-Wl,-T," + str(src / "tiger-minboot.ld"),
         "-Wl,-Map," + str(out / "tiger-minboot.map"), "-o", elf])
    run([tools["objcopy"], "-O", "binary", elf, raw])
    header = run([tools["readelf"], "-h", "-l", "-S", elf], "readelf.txt")
    assert "AArch64" in header and "Entry point address:               0x0" in header
    assert "INTERP" not in header
    nm = run([tools["nm"], "-n", elf], "nm.txt")
    symbols = {}
    for line in nm.splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    assert not run([tools["nm"], "-u", elf]).strip()
    run([tools["objdump"], "-d", elf], "disassembly.txt")
    assert symbols["_start"] == 0
    assert symbols["__data_load"] + (symbols["__data_end"] -
                                   symbols["__data_start"]) <= 0x100000
    assert 0x40000000 <= symbols["__data_start"] <= symbols["__data_end"]
    assert symbols["__bss_end"] <= 0x40010000
    assert symbols["__stack_top"] == 0x40020000
    assert 0 < raw.stat().st_size <= 0x100000
    manifest = {"build_id": build_id, "compiler": str(cc),
                "compiler_sha256": sha(cc), "compiler_version": version,
                "flags": flags, "source_files": {n: sha(src / n) for n in inputs},
                "symbols": symbols,
                "outputs": {n: {"sha256": sha(out / n),
                                "bytes": (out / n).stat().st_size}
                            for n in ("tiger-minboot.elf", "tiger-minboot.bin",
                                      "tiger-minboot.map", "readelf.txt",
                                      "nm.txt", "disassembly.txt")}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)

if __name__ == "__main__":
    main()
