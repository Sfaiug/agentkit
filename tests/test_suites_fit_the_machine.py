"""How many suite pieces start at once follows a piece's measured cost and the host's free CPU.

A repository's finished pieces leave their CPU cost behind, as each piece's box reported it,
and later pieces of that suite are sized by it; one with no record starts from the estimate.
CPU the host spends outside ak's slice -- ak's own menus, tick and live checks among it --
takes room the slice's quota would still promise.

Offline: temporary HOME, injected host readings and a fake cgroup tree; only the record test
runs real boxes, whose CPU is counted in CPU seconds, never against a wall clock.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.clock import Clock
from agentkit import box, gate, host, worker
import test_suite_pieces as fixture

# 6 idle cores and memory for many more: 8 pieces at the starting 0.7 CPU, 5 at 1.2.
ROOMY = {"cpus": 8, "load": 0, "free_mb": 32000, "slice_cpu_quota": 7, "slice_cpu_used": 1,
         "outside_cpu_used": 0, "slice_memory_high_mb": 32000, "slice_memory_used_mb": 0}
# A fifth of a second of its own CPU, however long the host makes that take.
BURN = 'python3 -c "import time; any(iter(lambda: time.process_time() >= 0.2, True))"'


class SuitesFitTheMachine(unittest.TestCase):
    def setUp(self):
        fixture.SuitePieces.setUp(self)

    def started(self, readings):
        """How many pieces one run of the suite starts, without a turn and, halved, with one."""
        counts = set()
        for turn in ("0", ""):
            shards = []
            def boxed(cmd, limit, env, **_kw):
                shards.append(env["AK_SHARD"])
                return 0, "", False
            with patch.object(worker, "boxed", side_effect=boxed), \
                    patch.dict(os.environ, {"AK_MAX_RUNS": turn,
                                            "AK_HOST_READINGS": json.dumps(readings)}):
                ok, text = fixture.SuitePieces.check(self)
            self.assertTrue(ok, text)
            counts.add(len(shards) // (1 if turn else 2))
        self.assertEqual(len(counts), 1, counts)
        return counts.pop()

    def checkout(self, name):
        """A repository of its own: the temporary HOME sits inside agentkit's checkout."""
        repo = self.root / name
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        return repo

    def test_a_recorded_cost_fits_fewer_pieces_in_the_same_free_cpu(self):
        self.assertEqual(self.started(ROOMY), int(6 / gate.HEAVY_CPUS))
        path, _, _ = gate.suite_cost(fixture.SUITE, self.root, self.run_dir)
        gate.write_suite_cost(path, {"cpus": 1.2})
        self.assertEqual(self.started(ROOMY), int(6 / 1.2))

    def test_a_repository_with_no_record_starts_from_the_estimate(self):
        path, _, _ = gate.suite_cost(fixture.SUITE, self.checkout("widget"), None)
        gate.write_suite_cost(path, {"cpus": 1.2})
        self.assertEqual(gate.suite_cost(fixture.SUITE, self.root, self.run_dir)[1:],
                         (gate.HEAVY_CPUS, gate.HEAVY_MEM_MB))
        self.assertEqual(self.started(ROOMY), int(6 / gate.HEAVY_CPUS))

    def test_cpu_used_outside_the_slice_lowers_the_count(self):
        # 8 cores less 4 outside leave the slice 4 of its quota's 7; it uses 1 of them.
        busy = {**ROOMY, "outside_cpu_used": 4}
        self.assertEqual(self.started(busy), int(3 / gate.HEAVY_CPUS))
        self.assertLess(self.started(busy), self.started(ROOMY))

    def test_the_host_reading_counts_cpu_outside_the_slice(self):
        root = self.root / "cgroups"
        part = root / "agentkit.slice"
        part.mkdir(parents=True)
        proc = self.root / "proc"
        proc.mkdir()
        (proc / "meminfo").write_text("MemAvailable: 33554432 kB\nMemTotal: 33554432 kB\n")
        (proc / "loadavg").write_text("0 0 0\n")

        def sleep(_delay):
            # one second of the host using 5 cores, 1 of them the slice's
            (root / "cpu.stat").write_text("usage_usec 5000000\n")
            (part / "cpu.stat").write_text("usage_usec 1000000\n")
        for quota in ("700000 100000\n", "max 100000\n"):
            with self.subTest(quota=quota):
                (part / "cpu.max").write_text(quota)
                for directory in (root, part):
                    (directory / "cpu.stat").write_text("usage_usec 0\n")
                clock = Clock(sleep)
                clock.monotonic = iter([100.0, 101.0]).__next__
                with patch.dict(os.environ, {"AK_HOST_READINGS": ""}), \
                        patch.object(host, "time", clock), patch.object(host, "PROC", proc), \
                        patch.object(host, "cpu_count", return_value=8):
                    readings = host.host_readings(cgroup_file=self.root / "no-cgroup",
                                                  cgroup_root=root, slice_dir=part)
                self.assertAlmostEqual(readings["slice_cpu_used"], 1)
                self.assertAlmostEqual(readings["outside_cpu_used"], 4)
                self.assertEqual(gate.derived_heavy_limit(readings, running=0),
                                 int(3 / gate.HEAVY_CPUS))

    def test_finished_pieces_leave_their_cost_behind(self):
        # Each piece burns once itself and once in a server it leaves running, as the line's
        # checker runs it: no run record, so no run cgroup, only the boxes' own reports.
        burnt = "burnt-${AK_SHARD%/*}"
        suite = (f"({BURN}; touch {burnt}; sleep 60) >/dev/null 2>&1 & {BURN}; "
                 f"until [ -e {burnt} ]; do sleep 0.1; done # AK_SHARD")
        repo = self.checkout("acme")
        reported, real = [], box.cpu_seconds
        def cpu_seconds(out_dir):
            reported.append(real(out_dir))
            return reported[-1]
        path, cpus, _ = gate.suite_cost(suite, repo, None)
        self.assertNotIn("cpus", gate.read_suite_cost(path))
        with patch.object(box, "cpu_seconds", side_effect=cpu_seconds):
            ok, text = gate.run_done_when([suite], repo, self.root / "line.log", set(),
                                          limit=600, heavy=True)
        self.assertTrue(ok, text)
        self.assertEqual(len(reported), text.count("--- AK_SHARD="))
        self.assertTrue(all(spent >= 0.4 for spent in reported), reported)
        measured = gate.read_suite_cost(path)["cpus"]
        self.assertGreaterEqual(measured, cpus)
        self.assertEqual(gate.suite_cost(suite, repo, None)[1], measured)


if __name__ == "__main__":
    unittest.main()
