"""The memory gate reads the nearest limit, outside reclaimable file cache."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run  # noqa: E402


def gb(n):
    return str(int(n * 1024 * 1024 * 1024))


def write_cgroup(root, rel, high=None, current=None, stat=None):
    directory = root / rel
    directory.mkdir(parents=True, exist_ok=True)
    if high is not None:
        (directory / "memory.high").write_text(high)
    if current is not None:
        (directory / "memory.current").write_text(current)
    if stat is not None:
        (directory / "memory.stat").write_text(stat)


def fixture(files, rel):
    """(cgroup_file, cgroup_root) under a fresh temp dir; the caller owns cleanup."""
    tmp = tempfile.mkdtemp(dir=REPO)
    root = Path(tmp) / "cgroup"
    root.mkdir()
    for relpath, content in files.items():
        write_cgroup(root, relpath, **content)
    cgroup_file = Path(tmp) / "proc_cgroup"
    cgroup_file.write_text(f"0::{rel}\n")
    return cgroup_file, root, tmp


class MemoryGate(unittest.TestCase):
    def tearDown(self):
        for tmp in getattr(self, "_tmps", []):
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def make(self, files, rel):
        cgroup_file, root, tmp = fixture(files, rel)
        self._tmps = getattr(self, "_tmps", []) + [tmp]
        return cgroup_file, root

    def test_nearest_limited_cgroup_wins_over_ancestor(self):
        cgroup_file, root = self.make({
            "user@1000.service": {"high": gb(11), "current": gb(10),
                                  "stat": "anon 0\nfile 0\n"},
            "user@1000.service/agentkit.slice": {"high": gb(10), "current": gb(5),
                                                 "stat": f"anon 0\nfile {gb(1)}\n"},
            "user@1000.service/agentkit.slice/agentkit-run-r.scope": {"high": "max"},
        }, "/user@1000.service/agentkit.slice/agentkit-run-r.scope")
        limits = run._unit_memory_limits(cgroup_file, root)
        self.assertEqual(len(limits), 1)
        used, high, raw, name = limits[0]
        self.assertEqual(name, "agentkit.slice")
        self.assertAlmostEqual(high, 10 * 1024, delta=0.01)
        self.assertAlmostEqual(raw, 5 * 1024, delta=0.01)
        self.assertAlmostEqual(used, 4 * 1024, delta=0.01)
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": limits}
        reason, _ = run._wait_reason(readings, 3072, 8)
        self.assertIsNone(reason)

    def test_file_cache_is_not_counted(self):
        cgroup_file, root = self.make({
            "user@1000.service": {"high": gb(11), "current": gb(9.5),
                                  "stat": f"anon 0\nfile {gb(5)}\n"},
        }, "/user@1000.service")
        limits = run._unit_memory_limits(cgroup_file, root)
        used, high, raw, _ = limits[0]
        self.assertAlmostEqual(raw, 9.5 * 1024, delta=0.01)
        self.assertAlmostEqual(used, 4.5 * 1024, delta=0.01)
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": limits}
        reason, _ = run._wait_reason(readings, 3072, 8)
        self.assertIsNone(reason)

    def test_inactive_file_counts_where_file_absent(self):
        cgroup_file, root = self.make({
            "agentkit.slice": {"high": gb(11), "current": gb(9.5),
                               "stat": f"anon 0\ninactive_file {gb(5)}\n"},
        }, "/agentkit.slice")
        limits = run._unit_memory_limits(cgroup_file, root)
        self.assertAlmostEqual(limits[0][0], 4.5 * 1024, delta=0.01)

    def test_waiting_line_shows_both_figures(self):
        cgroup_file, root = self.make({
            "agentkit.slice": {"high": gb(10), "current": gb(9.5),
                               "stat": f"anon 0\nfile {gb(1)}\n"},
        }, "/agentkit.slice")
        limits = run._unit_memory_limits(cgroup_file, root)
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": limits}
        reason, kind = run._wait_reason(readings, 3072, 8)
        self.assertEqual(reason, "waiting for the unit's memory · "
                                 "8.5 of 10 G in use (9.5 with cache)")
        self.assertEqual(kind, "unit memory")

    def test_truly_full_slice_still_waits(self):
        cgroup_file, root = self.make({
            "agentkit.slice": {"high": gb(10), "current": gb(9),
                               "stat": f"anon 0\nfile {gb(0.5)}\n"},
        }, "/agentkit.slice")
        limits = run._unit_memory_limits(cgroup_file, root)
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": limits}
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                     "AK_MAX_LOAD": "8"}), \
                patch.object(run, "slot_counts", return_value=(0, 0)), \
                patch.object(run, "process_owner", return_value={"pid": 1}), \
                patch.object(run, "host_readings", return_value=readings):
            self.assertFalse(run.claim_slot(state, 1))
        self.assertEqual(state["slot_wait_kind"], "unit memory")
        self.assertIn("in use", state["slot_wait_reason"])
        self.assertIn("with cache", state["slot_wait_reason"])

    def test_missing_memory_stat_fails_open(self):
        cgroup_file, root = self.make({
            "agentkit.slice": {"high": gb(10), "current": gb(9.5)},
        }, "/agentkit.slice")
        self.assertEqual(run._unit_memory_limits(cgroup_file, root), [])
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": []}
        reason, _ = run._wait_reason(readings, 3072, 8)
        self.assertIsNone(reason)

    def test_memory_stat_without_cache_counters_fails_open(self):
        cgroup_file, root = self.make({
            "agentkit.slice": {"high": gb(10), "current": gb(9.5),
                               "stat": "anon 100\nkernel 200\n"},
        }, "/agentkit.slice")
        self.assertEqual(run._unit_memory_limits(cgroup_file, root), [])

    def test_zero_high_still_gates(self):
        cgroup_file, root = self.make({
            "agentkit.slice": {"high": "0", "current": gb(1),
                               "stat": "anon 0\nfile 0\n"},
        }, "/agentkit.slice")
        limits = run._unit_memory_limits(cgroup_file, root)
        self.assertEqual(len(limits), 1)
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": limits}
        reason, kind = run._wait_reason(readings, 3072, 8)
        self.assertEqual(kind, "unit memory")
        self.assertEqual(reason, "waiting for the unit's memory · "
                                 "1 of 0 G in use (1 with cache)")
        keyed = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                 "unit_memory_current_mb": 100, "unit_memory_high_mb": 0}
        reason, kind = run._wait_reason(keyed, 3072, 8)
        self.assertEqual(kind, "unit memory")
        legacy = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                  "unit_limits": [(100, 0)]}
        reason, kind = run._wait_reason(legacy, 3072, 8)
        self.assertEqual(kind, "unit memory")

    def test_host_line_names_gating_cgroup(self):
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_limits": [(4096, 10240, 5120, "agentkit.slice")]}
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "8"}), \
                patch.object(run, "host_readings", return_value=readings):
            line = run.host_status_line()
        self.assertIn("agentkit.slice", line)
        self.assertIn("4 of 10 G in use", line)


if __name__ == "__main__":
    unittest.main()
