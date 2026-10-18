#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise deployment diagnostics without modifying the real deploy directory."""
import argparse
import configparser
import json
from pathlib import Path
import subprocess

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runqemu", required=True)
    ap.add_argument("--conf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "test-script.py").write_bytes(Path(__file__).read_bytes())
    original = args.conf.resolve()
    asset = original.name.removesuffix(".qemuboot.conf")
    identity = json.loads((original.parent / (asset + "-native-identity.json")).read_text())
    results = []
    for name in ("missing-bios", "missing-kernel", "unexpected-kernel"):
        case = out / name
        case.mkdir()
        conf = configparser.ConfigParser(interpolation=None)
        conf.read(original)
        for key, path in identity["paths"].items():
            conf.set("config_bsp", key, path)
        bios = original.parent / conf["config_bsp"]["qb_default_bios"]
        (case / bios.name).symlink_to(bios)
        # An empty KERNEL_IMAGETYPE would make the launcher's fallback glob
        # match any file, including this copied config. Isolate missing input.
        conf.set("config_bsp", "KERNEL_IMAGETYPE", "absent-kernel-image")
        if name == "missing-bios":
            conf.set("config_bsp", "QB_DEFAULT_BIOS", "does-not-exist.bin")
        elif name == "missing-kernel":
            conf.set("config_bsp", "QB_DEFAULT_KERNEL", "does-not-exist.bin")
        else:
            conf.set("config_bsp", "QB_DEFAULT_KERNEL", bios.name)
        config = case / (asset + ".qemuboot.conf")
        with config.open("w") as stream:
            conf.write(stream)
        trace = case / "instructions.log"
        argv = [args.runqemu, str(config), "nographic", "nonetwork",
                "qemuparams=-d in_asm -D " + str(trace)]
        result = subprocess.run(argv, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=30)
        (case / "output.log").write_text(result.stdout)
        instruction_bytes = trace.stat().st_size if trace.exists() else 0
        expected_rc = 0 if name == "unexpected-kernel" else 1
        diagnostic = ("tiger: kernel, initrd and DTB inputs are unsupported"
                      if name == "unexpected-kernel" else "not found")
        record = {"name": name, "argv": argv,
                  "launcher_returncode": result.returncode,
                  "expected_launcher_returncode": expected_rc,
                  "output": result.stdout, "instruction_bytes": instruction_bytes}
        record["pass"] = (result.returncode == expected_rc
                          and diagnostic in result.stdout
                          and "TIGER-CH4" not in result.stdout
                          and instruction_bytes == 0)
        if name == "unexpected-kernel":
            # The locked runqemu logs the child error but does not propagate
            # its status. A launcher rc=0 is explicitly not a successful boot.
            record["known_launcher_limitation"] = "QEMU refused input but runqemu returned zero"
            record["pass"] &= "Failed to run qemu:" in result.stdout
        results.append(record)
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    assert all(item["pass"] for item in results), results

if __name__ == "__main__":
    main()
