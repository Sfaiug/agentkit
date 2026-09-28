"""Every install re-derives agentkit's own slice ceiling, and a run's cap grows with it.

Offline: the `Installer` fakes from `test_slice` -- a fake `systemctl`, `nproc` and
`tmux` on PATH, a fake `/proc/meminfo`, a throwaway HOME -- and no real user manager.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run
from test_slice import Installer


class CeilingRewritten(Installer):
    def test_a_a_second_install_with_more_cores_rewrites_with_the_larger_quota(self):
        home = self.root / "bigger-home"
        home.mkdir()
        limits = home / ".config/systemd/user/agentkit.slice.d/limits.conf"
        first = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="4")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("CPUQuota=300%\n", limits.read_text())
        second = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="8")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("CPUQuota=700%\n", limits.read_text())

    def test_b_memory_is_written_as_shares(self):
        home = self.root / "shares-home"
        home.mkdir()
        result = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="4")
        self.assertEqual(result.returncode, 0, result.stderr)
        # 16 GiB of MemTotal on this host, and the file still says shares
        written = (home / ".config/systemd/user/agentkit.slice.d/limits.conf").read_text()
        self.assertIn("MemoryHigh=60%\nMemoryMax=70%\n", written)

    def test_c_a_pin_replaces_its_derived_value(self):
        home = self.root / "pinned-home"
        (home / ".agentkit").mkdir(parents=True)
        (home / ".agentkit/config.toml").write_text(
            'slice_tasks_max = 1024  # a bare number, verbatim\n'
            'slice_cpu_quota = "200%"\n')
        result = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="4")
        self.assertEqual(result.returncode, 0, result.stderr)
        written = (home / ".config/systemd/user/agentkit.slice.d/limits.conf").read_text()
        self.assertIn("TasksMax=1024\n", written)
        self.assertIn("CPUQuota=200%\n", written)
        self.assertIn("MemoryMax=70%\n", written)   # everything else is still derived

    def test_d_a_file_without_aks_first_line_is_left_byte_identical(self):
        home = self.root / "owned-home"
        home.mkdir()
        limits = home / ".config/systemd/user/agentkit.slice.d/limits.conf"
        limits.parent.mkdir(parents=True)
        owned = "[Slice]\nTasksMax=12\n# the owner's own hand\n"
        limits.write_text(owned)
        result = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="16")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(limits.read_text(), owned)
        self.assertIn("left byte-identical", result.stdout)
        for key in ("slice_tasks_max", "slice_memory_high", "slice_memory_max",
                    "slice_cpu_quota"):
            self.assertIn(key, result.stdout)

    def test_e_a_runs_cap_is_forty_percent_of_the_ceiling(self):
        self.assertEqual(run.memory_cap_mb(20000), 8000)

    def test_f_a_ceiling_from_the_old_wording_is_still_aks(self):
        home = self.root / "old-home"
        home.mkdir()
        limits = home / ".config/systemd/user/agentkit.slice.d/limits.conf"
        limits.parent.mkdir(parents=True)
        limits.write_text("# Written by agentkit's install.sh, once: the ceiling.\n"
                          "[Slice]\nTasksMax=12\nMemoryHigh=9830M\nMemoryMax=11468M\n"
                          "CPUQuota=100%\n")
        result = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="4")
        self.assertEqual(result.returncode, 0, result.stderr)
        rewritten = limits.read_text()
        self.assertIn("TasksMax=6144\n", rewritten)
        self.assertIn("MemoryHigh=60%\nMemoryMax=70%\n", rewritten)
        self.assertTrue(rewritten.startswith("# Written by agentkit's install.sh"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
