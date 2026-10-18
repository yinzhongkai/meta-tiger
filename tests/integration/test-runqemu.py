#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate formally deployed assets through the real locked runqemu launcher."""
import argparse
import configparser
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
import traceback

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runqemu", required=True, type=Path)
    ap.add_argument("--conf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--gdb", default="/usr/bin/gdb-multiarch")
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "test-script.py").write_bytes(Path(__file__).read_bytes())
    spec = importlib.util.spec_from_file_location("model_tools",
        Path(__file__).resolve().parents[1] / "model/test-tiger.py")
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    conf = args.conf.resolve()
    asset = conf.name.removesuffix(".qemuboot.conf")
    raw = conf.parent / (asset + ".bin")
    elf = conf.parent / (asset + ".elf")
    manifest = json.loads((conf.parent / (asset + "-manifest.json")).read_text())
    native = json.loads((conf.parent / (asset + "-native-identity.json")).read_text())
    syms = manifest["symbols"]
    expected_qemu = Path(native["qemu_path"])
    assert expected_qemu.is_file() and sha(expected_qemu) == native["qemu_sha256"]
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(conf)
    for key in ("qb_default_kernel", "qb_default_fstype", "qb_rootfs"):
        assert cp["config_bsp"][key] == "none"
    assert cp["config_bsp"]["qb_default_bios"] == raw.name
    sock = out / "qmp.sock"
    port_sock = socket.socket()
    port_sock.bind(("127.0.0.1", 0))
    port = port_sock.getsockname()[1]
    port_sock.close()
    params = ("-S -qmp unix:%s,server=on,wait=off -gdb tcp:127.0.0.1:%d "
              "-d in_asm,guest_errors -D %s -trace enable=pl011_*") % (
                  sock, port, out / "instructions.log")
    argv = [str(args.runqemu.resolve()), str(conf), "nographic", "nonetwork",
            "qemuparams=" + params]
    (out / "launcher-argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    log = out / "runqemu.log"
    output = log.open("w")
    p = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT,
                         stdin=subprocess.PIPE)
    q = None
    qemu_pid = None
    state = {"launcher_pid": p.pid, "argv": argv, "snapshots": [], "gdb": [],
             "qemu_sha256": sha(expected_qemu), "firmware_sha256": sha(raw),
             "configuration_sha256": sha(conf), "runqemu_sha256": sha(args.runqemu)}
    try:
        q = model.QMP(sock, p, out / "qmp.log")
        children = Path("/proc/%d/task/%d/children" % (p.pid, p.pid)).read_text().split()
        for pid in children:
            cmd = Path("/proc/%s/cmdline" % pid).read_bytes().rstrip(b"\0").split(b"\0")
            if cmd and cmd[0].decode() == str(expected_qemu):
                qemu_pid = int(pid)
                actual_argv = [c.decode() for c in cmd]
                break
        assert qemu_pid, children
        state["qemu_pid"] = qemu_pid
        state["actual_argv"] = actual_argv
        state["qemu_exe"] = str(Path("/proc/%d/exe" % qemu_pid).resolve())
        assert sha("/proc/%d/exe" % qemu_pid) == native["qemu_sha256"]
        for flag, value in (("-machine", "tiger"), ("-accel", "tcg"),
                ("-cpu", "cortex-a53"), ("-smp", "1"), ("-m", "1024"),
                ("-nic", "none"), ("-bios", str(raw))):
            assert actual_argv[actual_argv.index(flag) + 1] == value, actual_argv
        for forbidden in ("-device", "-netdev", "-drive", "-kernel", "-initrd",
                          "-dtb", "-append", "-enable-kvm"):
            assert forbidden not in actual_argv, actual_argv
        serials = [actual_argv[i + 1] for i, v in enumerate(actual_argv) if v == "-serial"]
        assert serials == ["mon:stdio", "null"], serials
        mtree = q.hmp("info mtree")
        (out / "mtree.txt").write_text(mtree)
        for region in ("tiger.rom", "tiger.ram", "pl011"):
            assert region in mtree, mtree
        for absent in ("gic", "pl031", "pl022", "tiger.sram"):
            assert absent not in mtree.lower(), mtree

        def reset_state(label):
            regs = q.hmp("info registers")
            assert re.search(r"PC=0{16}(?:\s|$)", regs) and "EL3h" in regs, regs
            uart = {hex(off): q.word(0x09000000 + off, 32)
                    for off in (0x18, 0x24, 0x28, 0x2c, 0x30, 0x38, 0x3c, 0x40)}
            assert uart == {"0x18": 0x90, "0x24": 0, "0x28": 0, "0x2c": 0,
                            "0x30": 0x300, "0x38": 0, "0x3c": 0, "0x40": 0}, uart
            cpus = q.command("query-cpus-fast")
            assert len(cpus) == 1
            props = {n: q.command("qom-get", {"path": cpus[0]["qom-path"], "property": n})
                     for n in ("rvbar", "has_el2", "has_el3", "cntfrq",
                               "start-powered-off", "psci-conduit")}
            assert props == {"rvbar": 0, "has_el2": True, "has_el3": True,
                             "cntfrq": 24000000, "start-powered-off": False,
                             "psci-conduit": 0}, props
            state["snapshots"].append({"label": label, "registers": regs,
                                      "uart": uart, "cpu_properties": props})

        def startup(label):
            commands = ["set pagination off", "set confirm off",
                "target remote 127.0.0.1:%d" % port,
                "hbreak *0x%x" % syms["firmware_main"], "continue",
                'printf "GDB_PC=0x%llx GDB_SP=0x%llx GDB_PSTATE=0x%llx\\n", $pc, $sp, $cpsr',
                'printf "GDB_DATA=0x%%llx\\n", *(unsigned long long*)0x%x' % syms["test_data"],
                'printf "GDB_BSS=0x%%llx\\n", *(unsigned long long*)0x%x' % syms["test_bss"],
                "delete breakpoints", "detach"]
            ga = [args.gdb, "-q", "-nx", "-batch", str(elf)]
            for command in commands:
                ga += ["-ex", command]
            (out / (label + "-gdb-argv.json")).write_text(json.dumps(ga, indent=2))
            r = subprocess.run(ga, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, timeout=30)
            (out / (label + "-gdb.log")).write_text(r.stdout)
            assert r.returncode == 0, r.stdout
            for expect in ("GDB_PC=0x%x" % syms["firmware_main"],
                           "GDB_SP=0x40020000", "GDB_DATA=0x1122334455667788", "GDB_BSS=0x0"):
                assert expect in r.stdout, r.stdout
            state["gdb"].append({"label": label, "rc": r.returncode, "output": r.stdout})
            q.command("cont")

        def marker(count):
            deadline = time.monotonic() + 20
            text = ""
            while time.monotonic() < deadline:
                text = log.read_text()
                if text.count("TIGER-CH4 FW=" + manifest["build_id"]) >= count:
                    break
                assert p.poll() is None, text
                time.sleep(0.05)
            assert text.count("CPU0 EL3 INIT=OK UART0 CFG=OK ROM=RO") >= count, text
            assert "FAIL" not in text and "Using host's QEMU" not in text, text
            q.command("stop")
            assert q.command("query-status")["status"] == "paused"
            assert q.word(syms["test_data"]) == 0xdadadadadadadada
            assert q.word(syms["test_bss"]) == 0xb0b0b0b0b0b0b0b0
            assert q.word(syms["observed_el"]) == 12
            assert q.word(syms["observed_mpidr"]) & 0xffffff == 0
            assert q.word(syms["observed_sctlr"]) & 0x1005 == 0
            sp = q.word(syms["observed_sp"])
            assert 0x40010000 <= sp <= 0x40020000 and sp % 16 == 0
            for off, val in ((0x24, 13), (0x28, 1), (0x2c, 0x60), (0x30, 0x101), (0x38, 0)):
                assert q.word(0x09000000 + off, 32) == val
            rom = out / ("rom-after-%d.bin" % count)
            q.command("pmemsave", {"val": 0, "size": 0x100000, "filename": str(rom)})
            assert rom.read_bytes() == raw.read_bytes().ljust(0x100000, b"\0")
            state["snapshots"].append({"label": "guest-%d" % count,
                "data": hex(q.word(syms["test_data"])), "bss": hex(q.word(syms["test_bss"])),
                "rom_sha256": sha(rom), "sp": hex(sp)})

        reset_state("cold-before-entry")
        startup("cold")
        marker(1)
        for index in range(2):
            since = len(q.events)
            q.command("system_reset")
            q.event("RESET", since)
            reset_state("reset-%d-before-cont" % (index + 1))
            assert q.word(syms["test_data"]) == 0xdadadadadadadada
            assert q.word(syms["test_bss"]) == 0xb0b0b0b0b0b0b0b0
            state["snapshots"][-1]["retained_data"] = hex(q.word(syms["test_data"]))
            state["snapshots"][-1]["retained_bss"] = hex(q.word(syms["test_bss"]))
            startup("warm-%d" % (index + 1))
            marker(index + 2)
        q.command("quit")
        state["launcher_exit_code"] = p.wait(timeout=15)
        assert p.returncode == 0
        trace = (out / "instructions.log").read_text()
        assert "0x00000000" in trace and "pl011_write" in trace
        assert len(re.findall(r"pl011_baudrate_change.*clk: 24000000hz", trace)) >= 6
        state["status"] = "pass"
    except Exception:
        state["status"] = "fail"
        state["traceback"] = traceback.format_exc()
        raise
    finally:
        if p.poll() is None:
            if q:
                try:
                    q.command("quit")
                except Exception:
                    pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if qemu_pid and Path("/proc/%d" % qemu_pid).exists():
                    import os
                    os.kill(qemu_pid, signal.SIGTERM)
                p.terminate()
                p.wait(timeout=5)
        if q:
            q.close()
        if p.stdin:
            p.stdin.close()
        output.close()
        state["final_launcher_returncode"] = p.returncode
        (out / "state.json").write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps(state), flush=True)

if __name__ == "__main__":
    main()
