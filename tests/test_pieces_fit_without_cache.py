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
        stack.enter_context(patch.object(config, "STATE", self.root / "state"))
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

    def memory(self, directory, current, file, shmem=0, cap=None):
        (directory / "memory.current").write_text(str(current * MB))
        (directory / "memory.stat").write_text(
            f"anon {(current - file) * MB}\nfile {file * MB}\nshmem {shmem * MB}\n")
        (directory / "memory.max").write_text("max" if cap is None else str(cap * MB))
        (directory / "memory.high").write_text("max")

    def lander_measures(self):
        """A suite of two pieces measured as a lander measures it, with no run of its own."""
        path, _, _ = gate.suite_cost(SUITE, self.root, None)
        self.memory(self.unit, 300, 200, shmem=20)
        measured = gate._SuiteMeasure(None)
        self.memory(self.unit, 2300, 1200, shmem=20)
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

    def test_reclaimable_cache_under_a_hard_cap_is_room_for_pieces(self):
        for file, shmem, pieces in ((2600, 100, 7), (2600, 2600, 2)):
            with self.subTest(file=file, shmem=shmem):
                self.memory(self.unit, 3000, file, shmem=shmem, cap=4096)
                self.memory(self.unit.parent, 3000, file, shmem=shmem)
                with patch.dict(os.environ, {"AK_HOST_READINGS": ""}):
                    readings = {**host.host_readings(), "cpus": 64, "free_mb": 64 * 1024}
                self.assertEqual(gate.derived_heavy_limit(
                    readings, running=0, job_mem_mb=500, unit=True), pieces)


if __name__ == "__main__":
    unittest.main()
