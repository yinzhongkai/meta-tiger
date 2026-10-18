#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the target fixture using the recipe's declared cross tools."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    for option in ("src", "out", "cc", "objcopy", "readelf", "nm", "objdump", "flags"):
        ap.add_argument("--" + option, required=True)
    ap.add_argument("--source-revision", required=True)
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    flags = shlex.split(args.flags)
    names = ("start.S", "main.c", "tiger-minboot.ld", "COPYING.MIT")
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode() + b"\0" + (src / name).read_bytes() + b"\0")
    digest.update(json.dumps(flags).encode())
    build_id = "sha256:" + digest.hexdigest()
    commands = []

    def run(argv, output=None):
        print("COMMAND", json.dumps([str(a) for a in argv]), flush=True)
        result = subprocess.run([str(a) for a in argv], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        commands.append({"argv": [str(a) for a in argv], "rc": result.returncode,
                         "output": result.stdout})
        (out / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        print(result.stdout, end="", flush=True)
        if output:
            (out / output).write_text(result.stdout)
        result.check_returncode()
        return result.stdout

    cc = shlex.split(args.cc)
    version = run(cc + ["--version"])
    elf, raw = out / "tiger-minboot.elf", out / "tiger-minboot.bin"
    run(cc + flags + ['-DTIGER_BUILD_ID="' + build_id + '"',
        str(src / "start.S"), str(src / "main.c"), "-Wl,--build-id=none",
        "-Wl,-T," + str(src / "tiger-minboot.ld"),
        "-Wl,-Map," + str(out / "tiger-minboot.map"), "-o", str(elf)])
    run(shlex.split(args.objcopy) + ["-O", "binary", str(elf), str(raw)])
    header = run(shlex.split(args.readelf) + ["-h", "-l", "-S", str(elf)], "readelf.txt")
    assert "AArch64" in header and "Entry point address:               0x0" in header
    assert "INTERP" not in header
    symbols = {}
    for line in run(shlex.split(args.nm) + ["-n", str(elf)], "nm.txt").splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = int(parts[0], 16)
    assert not run(shlex.split(args.nm) + ["-u", str(elf)]).strip()
    run(shlex.split(args.objdump) + ["-d", str(elf)], "disassembly.txt")
    assert symbols["_start"] == 0
    assert symbols["__data_load"] + symbols["__data_end"] - symbols["__data_start"] <= 0x100000
    assert 0x40000000 <= symbols["__data_start"] <= symbols["__data_end"]
    assert symbols["__bss_end"] <= 0x40010000
    assert symbols["__stack_top"] == 0x40020000
    assert 0 < raw.stat().st_size <= 0x100000
    outputs = ("tiger-minboot.bin", "tiger-minboot.elf", "tiger-minboot.map",
               "readelf.txt", "nm.txt", "disassembly.txt", "commands.json")
    manifest = {"build_id": build_id, "source_revision": args.source_revision,
                "compiler": cc, "compiler_version": version,
                "flags": flags, "source_files": {n: sha(src / n) for n in names},
                "symbols": symbols,
                "outputs": {n: {"bytes": (out / n).stat().st_size,
                                "sha256": sha(out / n)} for n in outputs}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)

if __name__ == "__main__":
    main()
