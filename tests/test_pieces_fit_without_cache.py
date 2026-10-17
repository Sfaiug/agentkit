"""A sharded suite runs as many pieces as memory fits: file cache the kernel reclaims is room,
under a hard cap too, and a lander measures its pieces' memory without that cache."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, host

MB = 1024 ** 2
SUITE = "python3 -m pytest # AK_SHARD"
CHILD, STRANGER = 4_000_001, 4_000_002


class PiecesFitWithoutCache(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix=".ak-test-pieces-cache-", dir=REPO)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.proc = self.root / "proc"
        for pid, parent in ((os.getpid(), 1), (CHILD, os.getpid()), (STRANGER, 1)):
            (self.proc / str(pid)).mkdir(parents=True)
            (self.proc / str(pid) / "stat").write_text(
                f"{pid} (python3) S {parent} {' '.join(['0'] * 30)}\n")
        stack.enter_context(patch.object(host, "PROC", self.proc))
        self.cgroups = self.root / "cgroups"
        self.unit = self.cgroups / "acme.slice" / "lander.service"
        self.unit.mkdir(parents=True)
        membership = self.root / "cgroup"
        membership.write_text("0::/acme.slice/lander.service\n")
        stack.enter_context(patch.dict(os.environ, {
            "AK_CGROUP_ROOT": str(self.cgroups), "AK_CGROUP_FILE": str(membership)}))
        self.holds(os.getpid(), CHILD)

    def holds(self, *pids):
        (self.unit / "cgroup.procs").write_text("".join(f"{pid}\n" for pid in pids))

    def memory(self, directory, current, lists, cap=None, **counters):
        """`lists` MB on the kernel's file lists, beside other memory.stat counters in MB."""
        (directory / "memory.current").write_text(str(current * MB))
        stat = {"active_file": 0, "inactive_file": lists, **counters}
        (directory / "memory.stat").write_text(
            "".join(f"{name} {value * MB}\n" for name, value in stat.items()))
        (directory / "memory.max").write_text("max" if cap is None else str(cap * MB))
        (directory / "memory.high").write_text("max")

    def lander_measures(self):
        """A suite of two pieces measured as a lander measures it, with no run of its own."""
        path, _, _ = gate.suite_cost(SUITE, self.root, None)
        self.memory(self.unit, 300, 180, file=200, shmem=20)
        measured = gate._SuiteMeasure(None)
        self.memory(self.unit, 2300, 1180, file=1200, shmem=20)
        measured.sample()
        measured.cpu.extend([10, 10])
        measured.save(path, 2)
        return gate.read_suite_cost(path)

    def test_a_lander_measures_its_pieces_without_the_file_cache(self):
        self.assertEqual(self.lander_measures()["mem_mb"], 500)
        self.assertEqual(gate.suite_cost(SUITE, self.root, None)[2], 500)

    def test_a_cgroup_holding_another_process_measures_no_memory(self):
        self.holds(os.getpid(), CHILD, STRANGER)
        self.assertNotIn("mem_mb", self.lander_measures())
        self.assertEqual(gate.suite_cost(SUITE, self.root, None)[2], gate.HEAVY_MEM_MB)

    def test_a_child_cgroup_whose_list_cannot_be_read_measures_no_memory(self):
        (self.unit / "other.service").mkdir()     # no list to read: it may hold any process
        self.assertNotIn("mem_mb", self.lander_measures())

    def test_reclaimable_cache_under_a_hard_cap_is_room_for_pieces(self):
        # tmpfs, shared memory and locked or ramfs pages are on no file list, and locked
        # anonymous memory, counted as unevictable too, is held once
        for lists, counters, pieces in ((2500, {"file": 2600, "shmem": 100}, 7),
                                        (0, {"file": 2600, "shmem": 2600}, 2),
                                        (0, {"file": 2600, "unevictable": 2600}, 2),
                                        (2000, {"file": 2000, "unevictable": 1000}, 6)):
            with self.subTest(lists=lists, **counters):
                self.memory(self.unit, 3000, lists, 4096, **counters)
                self.memory(self.unit.parent, 3000, lists, **counters)
                with patch.dict(os.environ, {"AK_HOST_READINGS": ""}):
                    readings = {**host.host_readings(), "cpus": 64, "free_mb": 64 * 1024}
                self.assertEqual(gate.derived_heavy_limit(
                    readings, running=0, job_mem_mb=500, unit=True), pieces)


if __name__ == "__main__":
    unittest.main()
