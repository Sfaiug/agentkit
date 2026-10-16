"""ak yields CPU by weight and can use every idle core unless its quota is pinned.

Offline: temporary HOME and cgroups, fake sudo/systemctl, injected host cores and load.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, host, status
import test_suite_pieces as suites
import test_user_unit_ceiling as fixture

READ_HOST = host.host_readings


class CpuPriority(unittest.TestCase):
    def setUp(self):
        self.installer = fixture.UserUnitCeiling()
        self.addCleanup(self.installer.doCleanups)
        self.installer.setUp()
        self.home = self.installer.root / "server-home"
        self.home.mkdir()
        self.slice = self.home / ".config/systemd/user/agentkit.slice.d/limits.conf"
        self.unit = self.installer.unit_limits()

    def install(self, **env):
        result = self.installer.install(self.home, **env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_priority(self, path):
        written = path.read_text()
        self.assertNotIn("CPUQuota=", written)
        weight = next(line.split("=", 1)[1] for line in written.splitlines()
                      if line.startswith("CPUWeight="))
        self.assertGreaterEqual(int(weight), 1)
        self.assertLess(int(weight), 100)  # systemd's default

    def test_install_uses_weights_on_small_and_large_hosts(self):
        for cpus in (1, 4, 16):
            with self.subTest(cpus=cpus):
                self.install(AK_SLICE_CPUS=str(cpus))
                for path in (self.slice, self.unit):
                    self.assert_priority(path)

    def test_old_ak_files_lose_their_quota(self):
        for path, section in ((self.slice, "Slice"), (self.unit, "Service")):
            path.parent.mkdir(parents=True)
            path.write_text("# Written by agentkit's install.sh, once: the ceiling.\n"
                            f"[{section}]\nCPUQuota=700%\n")
        self.install()
        for path in (self.slice, self.unit):
            self.assert_priority(path)

    def test_pin_keeps_a_slice_quota_and_removing_it_restores_priority(self):
        config_file = self.home / ".agentkit/config.toml"
        config_file.parent.mkdir()
        config_file.write_text('slice_cpu_quota = "200%"\n')
        self.install()
        self.assertIn("CPUQuota=200%\n", self.slice.read_text())
        self.assert_priority(self.unit)
        self.install(AK_SLICE_CPUS="16")
        self.assertIn("CPUQuota=200%\n", self.slice.read_text())
        config_file.write_text("")
        self.install()
        self.assert_priority(self.slice)

    def test_unmarked_files_are_left_byte_identical(self):
        owned = {self.slice: b"[Slice]\nCPUQuota=50%\n# owner's hand\r\n",
                 self.unit: fixture.HANDWRITTEN.encode()}
        for path, content in owned.items():
            path.parent.mkdir(parents=True)
            path.write_bytes(content)
        self.install()
        for path, content in owned.items():
            self.assertEqual(path.read_bytes(), content)

    def test_uncapped_gate_and_run_status_use_host_cores(self):
        root = self.installer.root
        proc = root / "proc"
        proc.mkdir()
        (proc / "meminfo").write_text("MemAvailable: 33554432 kB\nMemTotal: 33554432 kB\n")
        part = root / "cgroups/agentkit.slice"
        part.mkdir(parents=True)
        for quota in ("max 100000\n", None):
            if quota is None:
                (part / "cpu.max").unlink()
            else:
                (part / "cpu.max").write_text(quota)
            for cpus, load in ((1, 0), (8, 0), (8, 3), (8, 40), (32, 0)):
                with self.subTest(quota=quota, cpus=cpus, load=load):
                    (proc / "loadavg").write_text(f"{load} 0 0\n")
                    with patch.dict(os.environ, {"AK_HOST_READINGS": ""}), \
                            patch.object(host, "PROC", proc), \
                            patch.object(host, "cpu_count", return_value=cpus):
                        readings = READ_HOST(cgroup_file=root / "no-cgroup",
                                             cgroup_root=part.parent, slice_dir=part)
                    self.assertIsNone(readings["slice_cpu_quota"])
                    expected = max(1, int((cpus - load) / gate.HEAVY_CPUS))
                    self.assertEqual(gate.derived_heavy_limit(readings, running=0), expected)
                    output = io.StringIO()
                    with patch.object(host, "host_readings", return_value=readings), \
                            patch.object(gate, "_heavy_running", return_value=0), \
                            patch.object(config, "max_gates", return_value=None), \
                            redirect_stdout(output):
                        self.assertEqual(status.cmd_status([]), 0)
                    self.assertIn(f"host: {cpus} cpus", output.getvalue())
                    self.assertIn(f"heavy suites: {expected} at once (derived)", output.getvalue())

    def test_uncapped_landing_can_take_lower_weighted_build_cpu(self):
        pieces = suites.SuitePieces()
        self.addCleanup(pieces.doCleanups)
        pieces.setUp()
        whole, _ = pieces.cgroups({"lander-widget.scope": (host.CPU_WEIGHT_MAX, 0.0),
                                    "agentkit-run-build.scope": (40, 3.3)})
        (whole / "cpu.max").write_text("max 100000\n")
        proc = pieces.root / "proc"
        proc.mkdir()
        (proc / "meminfo").write_text("MemAvailable: 33554432 kB\nMemTotal: 33554432 kB\n")
        (proc / "loadavg").write_text("3.3 3.3 3.3\n")
        context = {"repo": str(pieces.root), "run_id": "widget", "landing": True, "since": 1}
        with patch.dict(os.environ, {"AK_MAX_RUNS": "", "AK_HOST_READINGS": ""}), \
                patch.object(host, "host_readings", READ_HOST), \
                patch.object(host, "PROC", proc), \
                patch.object(host, "cpu_count", return_value=4), \
                gate.gate_turn(None, pieces.root / "gate.log", None, suites.SUITE,
                               pieces.root, context=context):
            self.assertEqual(len(gate._GATE_HELD.hold.slots), int(4 / gate.HEAVY_CPUS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
