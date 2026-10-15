#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""QEMU model evidence; does not replace clean BitBake/runqemu validation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import traceback

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class QMP:
    def __init__(self, path, process, log):
        self.log = log.open("w")
        self.events = []
        self.seq = 0
        self.sock = socket.socket(socket.AF_UNIX)
        deadline = time.monotonic() + 15
        while True:
            try:
                self.sock.connect(str(path))
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("QMP unavailable; inspect qemu.stderr")
                time.sleep(0.05)
        self.sock.settimeout(15)
        self.file = self.sock.makefile("rwb")
        self.receive()
        self.command("qmp_capabilities")

    def receive(self):
        line = self.file.readline()
        if not line:
            raise EOFError("QMP disconnected")
        obj = json.loads(line)
        self.log.write("RX " + line.decode())
        self.log.flush()
        if "event" in obj:
            self.events.append(obj)
        return obj

    def command(self, name, arguments=None):
        self.seq += 1
        obj = {"execute": name, "id": self.seq}
        if arguments is not None:
            obj["arguments"] = arguments
        line = json.dumps(obj).encode() + b"\n"
        self.log.write("TX " + line.decode())
        self.log.flush()
        self.file.write(line)
        self.file.flush()
        while True:
            reply = self.receive()
            if reply.get("id") == self.seq:
                if "error" in reply:
                    raise RuntimeError(reply)
                return reply.get("return")

    def event(self, name, since):
        while not any(e["event"] == name for e in self.events[since:]):
            self.receive()

    def hmp(self, text):
        return self.command("human-monitor-command", {"command-line": text})

    def word(self, addr, bits=64):
        fmt = "g" if bits == 64 else "w"
        out = self.hmp("xp /1" + fmt + "x 0x%x" % addr)
        match = re.search(r":\s+0x([0-9a-fA-F]+)", out)
        assert match, out
        return int(match.group(1), 16)

    def close(self):
        self.file.close()
        self.sock.close()
        self.log.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", required=True, type=Path)
    ap.add_argument("--fixture", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--gdb", default="/usr/bin/gdb-multiarch")
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "test-script.py").write_bytes(Path(__file__).read_bytes())
    qemu = str(args.qemu.resolve())
    fixture = args.fixture.resolve()
    raw = fixture / "tiger-minboot.bin"
    elf = fixture / "tiger-minboot.elf"
    manifest = json.loads((fixture / "manifest.json").read_text())
    syms = manifest["symbols"]
    results = []
    common = [qemu, "-machine", "tiger", "-accel", "tcg",
              "-cpu", "cortex-a53", "-smp", "1", "-m", "1024",
              "-display", "none", "-monitor", "none", "-nic", "none"]

    def result(name, fn):
        try:
            details = fn()
            item = {"name": name, "status": "pass", "details": details}
        except Exception:
            item = {"name": name, "status": "fail", "traceback": traceback.format_exc()}
        results.append(item)
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(item), flush=True)

    def vm_test(name, bios, resets):
        d = out / name
        d.mkdir()
        serial = d / "uart.log"
        sock = d / "qmp.sock"
        port_sock = socket.socket()
        port_sock.bind(("127.0.0.1", 0))
        port = port_sock.getsockname()[1]
        port_sock.close()
        argv = common + ["-bios", str(bios), "-S", "-serial", "file:" + str(serial),
                         "-qmp", "unix:" + str(sock) + ",server=on,wait=off",
                         "-gdb", "tcp:127.0.0.1:%d" % port,
                         "-d", "in_asm,guest_errors", "-D", str(d / "instructions.log"),
                         "-trace", "enable=pl011_*"]
        (d / "argv.json").write_text(json.dumps(argv, indent=2))
        stderr = (d / "qemu.stderr").open("w")
        p = subprocess.Popen(argv, stdout=stderr, stderr=subprocess.STDOUT)
        q = None
        details = {"pid": p.pid, "argv": argv, "snapshots": [], "gdb": []}
        try:
            q = QMP(sock, p, d / "qmp.log")
            mtree = q.hmp("info mtree")
            (d / "mtree.txt").write_text(mtree)
            for expected in ("tiger.rom", "tiger.ram", "pl011"):
                assert expected in mtree, mtree
            for absent in ("gic", "pl031", "pl022", "tiger.sram"):
                assert absent not in mtree.lower(), mtree
            assert len(q.command("query-cpus-fast")) == 1

            def reset_state(label):
                regs = q.hmp("info registers")
                assert re.search(r"PC=0{16}(?:\s|$)", regs), regs
                assert "EL3h" in regs, regs
                uart = {hex(off): q.word(0x09000000 + off, 32)
                        for off in (0x18, 0x24, 0x28, 0x2c, 0x30, 0x38, 0x3c, 0x40)}
                assert uart == {"0x18": 0x90, "0x24": 0, "0x28": 0,
                                "0x2c": 0, "0x30": 0x300, "0x38": 0,
                                "0x3c": 0, "0x40": 0}, uart
                cpu_path = q.command("query-cpus-fast")[0]["qom-path"]
                props = {name: q.command("qom-get", {"path": cpu_path, "property": name})
                         for name in ("rvbar", "has_el2", "has_el3", "cntfrq",
                                      "start-powered-off", "psci-conduit")}
                assert props == {"rvbar": 0, "has_el2": True, "has_el3": True,
                                 "cntfrq": 24000000, "start-powered-off": False,
                                 "psci-conduit": 0}, props
                snap = {"label": label, "registers": regs, "uart": uart,
                        "cpu_properties": props}
                details["snapshots"].append(snap)
                return snap

            def init_break(label):
                commands = [
                    "set pagination off", "set confirm off",
                    "target remote 127.0.0.1:%d" % port,
                    "hbreak *0x%x" % syms["firmware_main"], "continue",
                    'printf "GDB_PC=0x%llx GDB_SP=0x%llx GDB_PSTATE=0x%llx\\n", $pc, $sp, $cpsr',
                    f'printf "GDB_DATA=0x%llx\\n", *(unsigned long long*)0x{syms["test_data"]:x}',
                    f'printf "GDB_BSS=0x%llx\\n", *(unsigned long long*)0x{syms["test_bss"]:x}',
                    "delete breakpoints", "detach"]
                argv = [args.gdb, "-q", "-nx", "-batch", str(elf)]
                for c in commands:
                    argv += ["-ex", c]
                (d / (label + "-gdb-argv.json")).write_text(json.dumps(argv, indent=2))
                try:
                    r = subprocess.run(argv, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, timeout=30)
                    text = r.stdout
                except subprocess.TimeoutExpired as e:
                    (d / (label + "-gdb.log")).write_bytes(e.stdout or b"")
                    raise
                (d / (label + "-gdb.log")).write_text(text)
                assert r.returncode == 0, text
                assert "GDB_PC=0x%x" % syms["firmware_main"] in text, text
                assert "GDB_SP=0x40020000" in text, text
                assert "GDB_DATA=0x1122334455667788" in text, text
                assert "GDB_BSS=0x0" in text, text
                details["gdb"].append({"label": label, "rc": r.returncode,
                                       "output": text})
                q.command("cont")

            def wait_marker(count):
                deadline = time.monotonic() + 15
                marker = "TIGER-CH4 FW=" + manifest["build_id"]
                while True:
                    text = serial.read_text() if serial.exists() else ""
                    if text.count(marker) >= count:
                        assert text.count("CPU0 EL3 INIT=OK UART0 CFG=OK ROM=RO") >= count, text
                        assert "FAIL" not in text, text
                        break
                    assert p.poll() is None, "QEMU exited"
                    assert time.monotonic() < deadline, "marker timeout: " + text
                    time.sleep(0.05)
                q.command("stop")
                assert q.command("query-status")["status"] == "paused"
                assert q.word(syms["test_data"]) == 0xdadadadadadadada
                assert q.word(syms["test_bss"]) == 0xb0b0b0b0b0b0b0b0
                assert q.word(syms["observed_el"]) == 12
                assert q.word(syms["observed_mpidr"]) & 0xffffff == 0
                assert q.word(syms["observed_sctlr"]) & 0x1005 == 0
                sp = q.word(syms["observed_sp"])
                assert 0x40010000 <= sp <= 0x40020000 and sp % 16 == 0
                for off, val in ((0x24, 13), (0x28, 1), (0x2c, 0x60),
                                 (0x30, 0x101), (0x38, 0)):
                    assert q.word(0x09000000 + off, 32) == val
                image = d / ("rom-after-%d.bin" % count)
                q.command("pmemsave", {"val": 0, "size": 0x100000,
                                      "filename": str(image)})
                assert image.read_bytes() == bios.read_bytes().ljust(0x100000, b"\0")
                details["snapshots"].append({"label": "guest-%d" % count,
                    "poison_data": hex(q.word(syms["test_data"])),
                    "poison_bss": hex(q.word(syms["test_bss"])),
                    "rom_sha256": sha(image), "sp": hex(sp)})

            reset_state("cold-before-entry")
            init_break("cold")
            wait_marker(1)
            for i in range(resets):
                since = len(q.events)
                q.command("system_reset")
                q.event("RESET", since)
                assert p.poll() is None
                snap = reset_state("reset-%d-before-cont" % (i + 1))
                # RAM retains sentinels until startup assembly reinitializes it.
                snap["retained_data"] = hex(q.word(syms["test_data"]))
                snap["retained_bss"] = hex(q.word(syms["test_bss"]))
                assert q.word(syms["test_data"]) == 0xdadadadadadadada
                assert q.word(syms["test_bss"]) == 0xb0b0b0b0b0b0b0b0
                assert len(q.command("query-cpus-fast")) == 1
                init_break("warm-%d" % (i + 1))
                wait_marker(i + 2)
            q.command("quit")
            details["exit_code"] = p.wait(timeout=10)
            assert details["exit_code"] == 0
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)
            details["final_returncode"] = p.returncode
            if q:
                q.close()
            stderr.close()
            details["serial"] = serial.read_text() if serial.exists() else ""
            details["stderr_sha256"] = sha(d / "qemu.stderr")
            details["trace_sha256"] = sha(d / "instructions.log") if (d / "instructions.log").exists() else None
            (d / "state.json").write_text(json.dumps(details, indent=2))
        trace = (d / "instructions.log").read_text()
        assert "pl011_write" in trace, "guest UART trace missing"
        clocks = re.findall(r"pl011_baudrate_change.*clk: 24000000hz", trace)
        assert len(clocks) >= 2 * (resets + 1), "PL011 clock/reset evidence missing"
        asm = trace
        assert "0x00000000" in asm, "entry instruction evidence missing"
        return details

    result("cold-and-two-warm-resets",
           lambda: vm_test("cold-and-two-warm-resets", raw, 2))
    exact = out / "exact-1MiB.bin"
    exact.write_bytes(raw.read_bytes().ljust(0x100000, b"\0"))
    result("exact-1MiB", lambda: vm_test("exact-1MiB", exact, 0))
    empty = out / "empty.bin"
    empty.write_bytes(b"")
    large = out / "too-large.bin"
    large.write_bytes(raw.read_bytes().ljust(0x100001, b"\0"))
    unreadable = out / "unreadable.bin"
    unreadable.write_bytes(raw.read_bytes())
    unreadable.chmod(0)
    directory = out / "directory-bios"
    directory.mkdir()

    def reject(name, extra, replace=None):
        d = out / name
        d.mkdir()
        argv = list(common)
        if replace:
            flag, val = replace
            argv[argv.index(flag) + 1] = val
        argv += ["-serial", "file:" + str(d / "uart.log"),
                 "-d", "in_asm", "-D", str(d / "instructions.log")] + extra
        (d / "argv.json").write_text(json.dumps(argv, indent=2))
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=15)
        (d / "output.log").write_text(r.stdout)
        expected = {
            "missing-bios-option": "a non-empty raw -bios image is required",
            "nonexistent-bios": "cannot find BIOS",
            "empty-bios": "BIOS must be readable raw data",
            "too-large-bios": "BIOS must be readable raw data",
            "unreadable-bios": "cannot find BIOS",
            "load-failure-directory": "BIOS must be readable raw data",
            "wrong-cpu": "Invalid CPU type",
            "wrong-smp": "Invalid SMP CPUs",
            "wrong-ram": "RAM must be exactly 1024 MiB",
            "ram-hotplug": "RAM must be exactly 1024 MiB",
            "wrong-accelerator": "only the TCG accelerator",
            "kernel-input": "kernel, initrd and DTB inputs are unsupported",
            "initrd-input": "-initrd only allowed with -kernel option",
            "dtb-input": "kernel, initrd and DTB inputs are unsupported"}
        assert r.returncode == 1, (r.returncode, r.stdout)
        assert expected[name] in r.stdout, r.stdout
        trace = d / "instructions.log"
        assert not trace.exists() or trace.stat().st_size == 0, "CPU executed"
        serial = d / "uart.log"
        assert not serial.exists() or serial.stat().st_size == 0, "guest output"
        return {"argv": argv, "exit_code": r.returncode, "output": r.stdout,
                "instruction_bytes": trace.stat().st_size if trace.exists() else 0}

    cases = [
        ("missing-bios-option", [], None),
        ("nonexistent-bios", ["-bios", str(out / "absent.bin")], None),
        ("empty-bios", ["-bios", str(empty)], None),
        ("too-large-bios", ["-bios", str(large)], None),
        ("unreadable-bios", ["-bios", str(unreadable)], None),
        ("load-failure-directory", ["-bios", str(directory)], None),
        ("wrong-cpu", ["-bios", str(raw)], ("-cpu", "cortex-a57")),
        ("wrong-smp", ["-bios", str(raw)], ("-smp", "2")),
        ("wrong-ram", ["-bios", str(raw)], ("-m", "512")),
        ("ram-hotplug", ["-bios", str(raw)], ("-m", "1024,maxmem=2G,slots=1")),
        ("wrong-accelerator", ["-bios", str(raw)], ("-accel", "qtest")),
        ("kernel-input", ["-bios", str(raw), "-kernel", str(raw)], None),
        ("initrd-input", ["-bios", str(raw), "-initrd", str(raw)], None),
        ("dtb-input", ["-bios", str(raw), "-dtb", str(raw)], None)]
    try:
        for name, extra, replace in cases:
            result(name, lambda n=name, e=extra, r=replace: reject(n, e, r))
    finally:
        unreadable.chmod(0o600)
    identity = {"qemu": qemu, "qemu_sha256": sha(qemu),
                "firmware": str(raw), "firmware_sha256": sha(raw),
                "manifest_sha256": sha(fixture / "manifest.json"),
                "test_script_sha256": sha(__file__)}
    (out / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(json.dumps({"passed": sum(r["status"] == "pass" for r in results),
                      "failed": sum(r["status"] != "pass" for r in results),
                      "identity": identity}), flush=True)
    raise SystemExit(0 if all(r["status"] == "pass" for r in results) else 1)

if __name__ == "__main__":
    main()
