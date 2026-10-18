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
    original = args.conf.resolve()
    asset = original.name.removesuffix(".qemuboot.conf")
    identity = json.loads((original.parent / (asset + "-native-identity.json")).read_text())
    results = []
    for name, key in (("missing-bios", "QB_DEFAULT_BIOS"),
                      ("missing-kernel", "QB_DEFAULT_KERNEL")):
        case = out / name
        case.mkdir()
        conf = configparser.ConfigParser(interpolation=None)
        conf.read(original)
        for k, path in identity["paths"].items():
            conf.set("config_bsp", k, path)
        bios = original.parent / conf["config_bsp"]["qb_default_bios"]
        (case / bios.name).symlink_to(bios)
        conf.set("config_bsp", key, "does-not-exist.bin")
        config = case / (asset + ".qemuboot.conf")
        with config.open("w") as stream:
            conf.write(stream)
        argv = [args.runqemu, str(config), "nographic", "nonetwork"]
        result = subprocess.run(argv, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=30)
        (case / "output.log").write_text(result.stdout)
        record = {"name": name, "argv": argv, "returncode": result.returncode,
                  "output": result.stdout}
        record["pass"] = result.returncode == 1 and "not found" in result.stdout.lower()
        record["pass"] &= "TIGER-CH4" not in result.stdout
        results.append(record)
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    assert all(item["pass"] for item in results), results

if __name__ == "__main__":
    main()
