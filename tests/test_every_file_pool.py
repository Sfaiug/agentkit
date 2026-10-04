"""The file sweep grows with memory and pauses each start during live CPU contention.

Offline: injected readings, controlled futures and cgroup files in a temporary HOME.
"""

from concurrent.futures import Future
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import every_file
from agentkit import host

CALM = {"cpus": 8, "load": 50, "cpu_pressure": 12, "free_mb": 4600}


class EveryFilePool(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-every-file-pool-", dir=REPO)))
        self.enterContext(patch.dict(os.environ, {"HOME": str(self.root)}))

    def test_waiters_can_outnumber_cores_and_scale_with_memory(self):
        small = every_file.pool_limit(CALM)
        large = every_file.pool_limit({**CALM, "free_mb": 9200})
        self.assertGreater(small, CALM["cpus"])
        self.assertEqual(large, 2 * small)
        # A CPU quota is not a cost per waiting file either.
        self.assertEqual(every_file.pool_limit({**CALM, "slice_cpu_quota": 2,
                                               "slice_cpu_used": 0.1}), small)

    def test_background_stalls_allow_growth_up_to_the_pressure_ceiling(self):
        # Nonzero readings are normal on an idle-ish host; none can require a zero sample.
        for pressure in (0.01, 2, 3, 12, 20):
            with self.subTest(pressure=pressure):
                self.assertGreater(every_file.pool_limit(
                    {**CALM, "cpu_pressure": pressure}), CALM["cpus"])

    def test_high_pressure_overrides_even_the_serial_floor(self):
        for free in (0, 4600):
            for pressure in (20.01, 50, 100):
                with self.subTest(free=free, pressure=pressure):
                    self.assertEqual(every_file.pool_limit(
                        {**CALM, "free_mb": free, "cpu_pressure": pressure}), 0)
        self.assertEqual(every_file.pool_limit({**CALM, "slice_cpu_quota": 2,
                                               "slice_cpu_used": 2}), 0)

    def test_every_memory_bound_applies_including_an_enclosing_cgroup(self):
        for extra in ({"free_mb": 460},
                      {"slice_memory_high_mb": 1000, "slice_memory_used_mb": 540},
                      {"unit_memory_high_mb": 1000, "unit_memory_current_mb": 540},
                      {"unit_limits": [[0, 10000], [540, 1000]]}):
            with self.subTest(extra=extra):
                self.assertEqual(every_file.pool_limit({**CALM, **extra}), 2)

    def test_unreadable_or_small_hosts_stay_serial(self):
        for readings in ({}, {"free_mb": 4600}, {"cpu_pressure": 12},
                         {**CALM, "free_mb": 10}):
            with self.subTest(readings=readings):
                self.assertEqual(every_file.pool_limit(readings), 1)

    def sweep(self, snapshots, count=6, finish_each=False):
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "smoke.sh").write_text("#!/bin/bash\n")
        for n in range(count):
            (tests / f"test_acme_{n}.py").write_text('print("TESTS_RUN=1")\n')
        starts, futures, polls = [], [], []

        def reading(**_kw):
            self.assertLess(len(polls), 30, "the sweep stopped admitting files")
            snapshot = snapshots[min(len(polls), len(snapshots) - 1)]
            polls.append(snapshot)
            return snapshot

        def submit(_run, root, path, env, **_kw):
            starts.append((path.name, len(polls)))
            future = Future()
            futures.append(future)
            return future

        def finish(_running, **_kw):
            if finish_each or len(starts) == count:
                for future in futures:
                    if not future.done():
                        future.set_result((0, "TESTS_RUN=1\n", 49))

        out = io.StringIO()
        with patch.object(host, "host_readings", side_effect=reading), \
                patch.object(every_file, "ThreadPoolExecutor") as pool, \
                patch.object(every_file, "wait", side_effect=finish), \
                patch.object(every_file.time, "sleep"), redirect_stdout(out):
            pool.return_value.__enter__.return_value.submit.side_effect = submit
            self.assertEqual(every_file.main(self.root), 0)
        self.assertCountEqual([name for name, _ in starts],
                              [f"test_acme_{n}.py" for n in range(count)])
        self.assertEqual(out.getvalue().count("PASS  tests/"), count)
        return [poll for _, poll in starts], out.getvalue()

    def test_pressure_and_memory_are_reread_before_each_start(self):
        starts, out = self.sweep([
            {**CALM, "cpu_pressure": 40},  # even the first file must wait
            CALM,                        # first file starts
            {**CALM, "cpu_pressure": 21},  # no queued file bypasses high pressure
            {**CALM, "cpu_pressure": 50},
            CALM,                        # second file starts
            {**CALM, "free_mb": 230},     # existing files keep their reservations
            {**CALM, "free_mb": 230},
            CALM])                       # memory recovered; the pool grows again
        self.assertEqual(starts, [2, 5, 8, 9, 10, 11])
        self.assertIn(", 6 at once,", out)

    def test_persistent_background_stalls_let_a_sweep_start_and_grow(self):
        starts, out = self.sweep([CALM], count=9)
        self.assertEqual(starts, list(range(1, 10)))
        self.assertIn(", 9 at once,", out)

    def test_losing_cpu_readings_stops_growth_without_stranding_files(self):
        starts, out = self.sweep([CALM, {"free_mb": 4600}], finish_each=True)
        self.assertEqual(starts, list(range(1, 7)))
        self.assertIn(", 1 at once,", out)

    def test_an_empty_sweep_needs_no_host_readings(self):
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "smoke.sh").write_text("#!/bin/bash\n")
        with patch.object(host, "host_readings", side_effect=AssertionError("host read")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(every_file.main(self.root), 0)

    def pressure_file(self, path, total):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"some avg10=90.00 avg60=80.00 avg300=70.00 total={total}\n"
                        "full avg10=0.00 avg60=0.00 avg300=0.00 total=999999999\n")

    def test_pressure_measures_current_stalls_over_actual_elapsed_time(self):
        system, scope = self.root / "cpu", self.root / "cpu.pressure"
        self.pressure_file(system, 100000)
        self.pressure_file(scope, 200000)

        def advance(_delay):
            self.pressure_file(system, 110000)
            self.pressure_file(scope, 240000)

        with patch.object(host.time, "sleep", side_effect=advance), \
                patch.object(host.time, "monotonic", side_effect=[10, 10.2]):
            # Wakeup took twice the requested window; the busiest group's current rate wins.
            self.assertAlmostEqual(host._cpu_pressure({system, scope}, 0.1), 20)

    def test_old_average_does_not_hide_recovery_and_bad_counters_are_unknown(self):
        path = self.root / "cpu"
        self.pressure_file(path, 100000)
        with patch.object(host.time, "sleep"), \
                patch.object(host.time, "monotonic", side_effect=[10, 10.1]):
            self.assertEqual(host._cpu_pressure({path}, 0.1), 0)
        with patch.object(host.time, "sleep", side_effect=lambda _: self.pressure_file(path, 1)), \
                patch.object(host.time, "monotonic", side_effect=[10, 10.1]):
            self.assertIsNone(host._cpu_pressure({path}, 0.1))
        path.write_text("some total=broken\n")
        self.assertIsNone(host._cpu_pressure({path}, 0.1))
        path.unlink()
        self.assertIsNone(host._cpu_pressure({path}, 0.1))

    def test_live_readings_include_host_and_scope_pressure_and_all_memory_caps(self):
        proc, cgroups = self.root / "proc", self.root / "cgroups"
        scope = cgroups / "acme.slice/fix-api.scope"
        scope.mkdir(parents=True)
        proc.mkdir()
        (proc / "meminfo").write_text("MemAvailable: 4710400 kB\nMemTotal: 8388608 kB\n")
        (proc / "loadavg").write_text("50 40 30 1/10 123\n")
        membership = self.root / "cgroup"
        membership.write_text("0::/acme.slice/fix-api.scope\n")
        for group, high, hard, used in ((scope, "max", 2300, 460),
                                        (scope.parent, "4600", 23000, 4140)):
            (group / "memory.high").write_text(
                high if high == "max" else str(int(high) * 1024 * 1024))
            (group / "memory.max").write_text(str(hard * 1024 * 1024))
            (group / "memory.current").write_text(str(used * 1024 * 1024))
            (group / "memory.stat").write_text("file 0\n")
        system = proc / "pressure/cpu"
        self.pressure_file(system, 100000)
        self.pressure_file(scope / "cpu.pressure", 200000)

        def advance(_delay):
            self.pressure_file(system, 100000)
            self.pressure_file(scope / "cpu.pressure", 205000)

        with patch.object(host, "PROC", proc), patch.object(host, "cpu_count", return_value=8), \
                patch.dict(os.environ, {"AK_HOST_READINGS": ""}), \
                patch.object(host.time, "sleep", side_effect=advance), \
                patch.object(host.time, "monotonic", side_effect=[10, 10.1]):
            readings = host.host_readings(cgroup_file=membership, cgroup_root=cgroups,
                                          slice_dir=scope.parent, pressure_window=0.1,
                                          all_limits=True)
        self.assertAlmostEqual(readings["cpu_pressure"], 5)
        self.assertEqual(len(readings["unit_limits"]), 2)
        self.assertEqual(every_file.pool_limit(readings), 2)
        # Existing callers keep the nearest soft limit, rather than changing run admission.
        self.assertEqual(host._unit_memory_limits(membership, cgroups),
                         [(4140, 4600, 4140, "acme.slice")])

    def test_injected_readings_bypass_every_real_host_read(self):
        with patch.dict(os.environ, {"AK_HOST_READINGS": '{"cpu_pressure": 12, "free_mb": 4600}'}), \
                patch.object(Path, "read_text", side_effect=AssertionError("real host read")), \
                patch.object(host.time, "sleep", side_effect=AssertionError("real sample")):
            readings = host.host_readings(slice_dir=lambda: self.fail("real cgroup"),
                                          pressure_window=0.1, all_limits=True)
        self.assertEqual(every_file.pool_limit(readings), 20)


if __name__ == "__main__":
    unittest.main()
