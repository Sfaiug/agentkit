"""Seats yield CPU and I/O to runs, and their CPU never closes the run gate.

Offline: temporary HOME, fake systemctl, injected AK_HOST_READINGS, and a fake
cgroup tree for the sampler. No real slice or process is changed.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, host, orch, record, run

CALM = {"cpus": 8, "load": 100, "free_mb": 16000, "mem_total_mb": 32000,
        "slice_cpu_pressure": 0, "slice_cpu_used": 0, "slice_cpu_quota": 8,
        "outside_cpu_used": 0}
SYSTEMCTL = '''#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
if args == ["--user", "is-system-running"]:
    print("running")
elif args[:1] == ["show"]:
    print("8192")
elif "set-property" in args:
    path = pathlib.Path(os.environ["FAKE_UNITS"])
    units = json.loads(path.read_text())
    unit = next(arg for arg in args if arg.endswith(".slice"))
    units.setdefault(unit, {{}}).update(arg.split("=", 1) for arg in args if "=" in arg)
    path.write_text(json.dumps(units))
'''


class SeatsYieldCpu(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seats-yield-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / ".config"),
            orch.SOCKET_ENV: orch.SOCKET, "AK_HOST_READINGS": json.dumps(CALM),
            "AK_MIN_FREE_MB": "3072", "AK_MAX_RUNS": "1"}))
        os.environ.pop("AK_MAX_LOAD", None)
        for name in ("HOME", "RUNS"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
            getattr(config, name).mkdir()
        self.stack.enter_context(patch.object(gate, "slot_counts", return_value=(0, 0, [])))
        self.stack.enter_context(patch.object(gate, "landing_waits", return_value=False))
        self.stack.enter_context(patch.object(record, "process_owner", return_value={"pid": 42}))
        self.stack.enter_context(patch.object(orch, "scope_oom_policy", return_value=True))

    def test_install_updates_new_and_already_open_seats(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        ctl = bindir / "systemctl"
        ctl.write_text(SYSTEMCTL.format(python=sys.executable))
        ctl.chmod(0o755)
        units = self.root / "units.json"
        units.write_text(json.dumps({orch.SEATS_SLICE: {"CPUWeight": "100", "IOWeight": "100"}}))
        home = self.root / ".agentkit"
        home.mkdir()
        (home / "config.toml").write_text('slice_memory_max = "10000M"\n')
        source = (REPO / "install.sh").read_text()
        body = source[source.index("# --- (g3) the ceiling"):source.index("# --- (h) a new phone key")]
        prelude = ("set -euo pipefail\nROLE=server\nSANDBOX=0\n"
                   f"REPO={shlex.quote(str(REPO))}\n"
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "$*" >&2; }\n')
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    dropin.write_text("# Written by agentkit's install.sh\n[Slice]\n"
                                      "CPUWeight=100\nIOWeight=100\nMemoryLow=30%\n")
                    units.write_text(json.dumps({orch.SEATS_SLICE: {
                        "CPUWeight": "100", "IOWeight": "100"}}))
                result = subprocess.run(["bash", "-c", prelude + body], capture_output=True,
                                        text=True, timeout=30, env={**os.environ,
                                        "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_UNITS": str(units)})
                self.assertEqual(result.returncode, 0, result.stderr)
                dropin = self.root / ".config/systemd/user/agentkit-seats.slice.d/weights.conf"
                seats = dict(line.split("=", 1) for line in dropin.read_text().splitlines() if "=" in line)
                runs = self.root / ".config/systemd/user/agentkit-runs.slice.d/weights.conf"
                runs = dict(line.split("=", 1) for line in runs.read_text().splitlines() if "=" in line)
                live = json.loads(units.read_text())
                for key in ("CPUWeight", "IOWeight"):
                    self.assertLess(int(seats[key]), int(runs[key]))
                    self.assertEqual(live[orch.SEATS_SLICE][key], seats[key])
                    self.assertEqual(live[orch.RUNS_SLICE][key], runs[key])
                _, properties = run.run_scope_limits(cap_mb=1000)
                self.assertLess(int(next(p.split("=")[1] for p in properties if p.startswith("CPUWeight="))),
                                host.CPU_WEIGHT_MAX)

    def readings_by_slice(self, runs):
        parent = self.root / "agentkit.slice"
        self.stack.enter_context(patch.object(orch, "slice_cgroup", return_value=parent))
        original = host.host_readings
        def readings(*args, **kwargs):
            cpu_dir = kwargs.get("cpu_dir", kwargs.get("slice_dir"))()
            data = runs if cpu_dir == parent / orch.RUNS_SLICE else {
                **CALM, "slice_cpu_pressure": 99, "slice_cpu_used": 8}
            with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(data)}):
                return original(*args, **kwargs)
        self.stack.enter_context(patch.object(host, "host_readings", side_effect=readings))

    def test_busy_seats_do_not_hold_a_queued_run(self):
        self.readings_by_slice(CALM)
        state = {"run_id": "acme", "state": "queued"}
        self.assertFalse(gate.claim_slot(state, 1))  # first steady poll
        self.assertTrue(gate.claim_slot(state, 1), state)

    def test_busy_runs_hold_a_queued_run(self):
        self.readings_by_slice({**CALM, "slice_cpu_pressure": 99})
        state = {"run_id": "acme", "state": "queued"}
        for _ in range(3):
            self.assertFalse(gate.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_kind"], "cpu")

    def test_heavy_room_and_status_read_runs_cpu(self):
        self.readings_by_slice(CALM)
        self.assertEqual(gate.derived_heavy_limit(running=0), int(8 / gate.HEAVY_CPUS))
        line = gate.host_status_line()
        self.assertIn("runs cpu 0%", line)
        self.assertIn("runs cpu ≤ 40%", line)

    def test_host_memory_still_holds_a_run(self):
        self.readings_by_slice({**CALM, "free_mb": 1024})
        state = {"run_id": "acme", "state": "queued"}
        self.assertFalse(gate.claim_slot(state, 1))
        self.assertEqual(state["slot_wait_kind"], "memory")

    def test_sampler_keeps_shared_memory_and_excludes_seats_from_outside_cpu(self):
        root = self.root / "cgroups"
        parent = root / "agentkit.slice"
        runs = parent / orch.RUNS_SLICE
        runs.mkdir(parents=True)
        proc = self.root / "proc"
        proc.mkdir()
        (proc / "meminfo").write_text("MemAvailable: 16384000 kB\nMemTotal: 32768000 kB\n")
        (proc / "loadavg").write_text("100 100 100\n")
        (parent / "cpu.max").write_text("600000 100000\n")
        (parent / "memory.high").write_text(str(12000 * 1024**2))
        (parent / "memory.current").write_text(str(1000 * 1024**2))
        (parent / "memory.stat").write_text("inactive_file 0\n")
        (parent / "cpu.pressure").write_text("some avg10=99\n")
        (runs / "cpu.pressure").write_text("some avg10=0\n")
        with patch.dict(os.environ, {"AK_HOST_READINGS": ""}), \
                patch.object(host, "PROC", proc), patch.object(host, "cpu_count", return_value=8), \
                patch.object(host, "_cpu_rates", return_value={root: 8, parent: 7, runs: 1}) as sample:
            readings = host.host_readings(cgroup_file=self.root / "no-cgroup", cgroup_root=root,
                                          slice_dir=parent, cpu_dir=runs)
        self.assertEqual(set(sample.call_args.args[0]), {root, parent, runs})
        self.assertEqual(readings["slice_cpu_pressure"], 0)
        self.assertEqual(readings["slice_cpu_used"], 1)
        self.assertEqual(readings["outside_cpu_used"], 1)
        self.assertEqual(readings["slice_cpu_quota"], 6)
        self.assertEqual(readings["slice_memory_used_mb"], 1000)
        self.assertEqual(readings["slice_memory_high_mb"], 12000)
        self.assertEqual(readings["free_mb"], 16000)
        # Before the first run there is no runs cgroup; busy seats still leave CPU room.
        with patch.dict(os.environ, {"AK_HOST_READINGS": ""}), \
                patch.object(host, "PROC", proc), patch.object(host, "cpu_count", return_value=8), \
                patch.object(host, "_cpu_rates", return_value={root: 8, parent: 7}):
            readings = host.host_readings(cgroup_file=self.root / "no-cgroup", cgroup_root=root,
                                          slice_dir=parent, cpu_dir=parent / "not-started.slice")
        self.assertEqual(readings["slice_cpu_used"], 0)
        self.assertEqual(gate.derived_heavy_limit(readings, running=0), int(6 / gate.HEAVY_CPUS))


if __name__ == "__main__":
    unittest.main()
