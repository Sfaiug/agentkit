"""Admission reads ak's own slice CPU pressure, not the host's load average.

A run starts while the slice has CPU room whatever the host load is, waits
while the slice itself is saturated, and --first skips the CPU check as it
skipped load; a pinned max_load restores the old host-load check. Offline: a
throwaway HOME, mocked slot counts, and injected host readings. The real
machine's load, pressure and cgroups are never read.
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import host, config, run  # noqa: E402

READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000,
            "slice_cpu_pressure": 5,
            "slice_cpu_stat": {"usage_usec": 1878241940777, "nr_periods": 5378937,
                               "nr_throttled": 290683, "throttled_usec": 1831801260}}


class AdmissionSliceCpu(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-admission-slice-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # no config.toml here, so max_load is unpinned unless the test writes one
        self.stack.enter_context(patch.object(config, "HOME", self.root))
        self.stack.enter_context(patch.object(config, "RUNS", self.root / "runs"))
        self.stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": "1",
                                                         "AK_MIN_FREE_MB": "3072"}))
        os.environ.pop("AK_MAX_LOAD", None)
        self.stack.enter_context(patch.object(run, "slot_counts", return_value=(0, 0)))
        self.stack.enter_context(patch.object(run, "frozen_runs", return_value=0))
        self.stack.enter_context(patch.object(run, "process_owner",
                                              return_value={"pid": 1}))

    def claim(self, readings, state=None):
        state = {"run_id": "r", "run_depth": 0, **(state or {})}
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(readings)}):
            return run.claim_slot(state, 1), state

    def test_high_host_load_with_idle_slice_admits(self):
        loaded = {**READINGS, "load": 41, "slice_cpu_pressure": 5}
        admitted, state = self.claim(loaded)
        self.assertFalse(admitted)  # first steady poll
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for steady readings · 4 G free, ak cpu pressure 5%")
        self.assertNotIn("slot_wait_kind", state)
        admitted, state = self.claim(loaded, state)
        self.assertTrue(admitted)
        self.assertEqual(state["state"], "running")

    def test_saturated_slice_waits_then_admits_after_two_healthy_polls(self):
        admitted, state = self.claim({**READINGS, "slice_cpu_pressure": 62})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for ak's CPU · pressure 62%, limit 40%")
        self.assertEqual(state["slot_wait_kind"], "cpu")
        admitted, state = self.claim(READINGS, state)
        self.assertFalse(admitted)
        admitted, state = self.claim(READINGS, state)
        self.assertTrue(admitted)
        self.assertEqual(state["state"], "running")

    def test_memory_floor_still_gates(self):
        admitted, state = self.claim({**READINGS, "free_mb": 1024,
                                      "slice_cpu_pressure": 5})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_kind"], "memory")

    def test_first_skips_slice_cpu_gate(self):
        hot = {**READINGS, "slice_cpu_pressure": 90}
        admitted, state = self.claim(hot, {"first": True})
        self.assertFalse(admitted)  # first steady poll
        self.assertNotIn("slot_wait_kind", state)
        admitted, state = self.claim(hot, state)
        self.assertTrue(admitted)
        self.assertEqual(state["state"], "running")

    def test_pinned_max_load_in_config_restores_load_check(self):
        (self.root / config.CONFIG_NAME).write_text("max_load = 8\n")
        admitted, state = self.claim({**READINGS, "load": 41,
                                      "slice_cpu_pressure": 5})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for the host to calm · load 41, limit 8")
        self.assertEqual(state["slot_wait_kind"], "load")
        # and under the pin the slice's own pressure gates nothing
        calm = {**READINGS, "load": 1, "slice_cpu_pressure": 90}
        admitted, state = self.claim(calm)
        self.assertFalse(admitted)  # first steady poll
        admitted, state = self.claim(calm, state)
        self.assertTrue(admitted)

    def test_pinned_max_load_in_environment_restores_load_check(self):
        with patch.dict(os.environ, {"AK_MAX_LOAD": "8"}):
            admitted, state = self.claim({**READINGS, "load": 41,
                                          "slice_cpu_pressure": 5})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for the host to calm · load 41, limit 8")
        self.assertEqual(state["slot_wait_kind"], "load")

    def test_pinned_zero_disables_cpu_check(self):
        with patch.dict(os.environ, {"AK_MAX_LOAD": "0"}):
            readings = {**READINGS, "load": 400, "slice_cpu_pressure": 99}
            admitted, state = self.claim(readings)
            self.assertFalse(admitted)  # first steady poll
            admitted, state = self.claim(readings, state)
        self.assertTrue(admitted)
        self.assertEqual(state["state"], "running")

    def test_slice_pressure_reads_some_avg10(self):
        slice_dir = self.root / "agentkit.slice"
        slice_dir.mkdir()
        (slice_dir / "cpu.pressure").write_text(
            "some avg10=24.01 avg60=32.25 avg300=41.39 total=115793455101\n"
            "full avg10=2.73 avg60=3.79 avg300=5.51 total=30965092215\n")
        self.assertEqual(host._slice_cpu_pressure(slice_dir), 24.01)
        (slice_dir / "cpu.pressure").unlink()
        self.assertIsNone(host._slice_cpu_pressure(slice_dir))
        (slice_dir / "cpu.pressure").write_text("some avg10=banana\n")
        self.assertIsNone(host._slice_cpu_pressure(slice_dir))

    def test_slice_stat_exposes_counters(self):
        slice_dir = self.root / "agentkit.slice"
        slice_dir.mkdir()
        (slice_dir / "cpu.stat").write_text(
            "usage_usec 1878241940777\nuser_usec 1337642420232\n"
            "system_usec 540599520545\nnr_periods 5378937\n"
            "nr_throttled 290683\nthrottled_usec 1831801260\n")
        self.assertEqual(host._slice_cpu_stat(slice_dir), {
            "usage_usec": 1878241940777, "user_usec": 1337642420232,
            "system_usec": 540599520545, "nr_periods": 5378937,
            "nr_throttled": 290683, "throttled_usec": 1831801260})
        (slice_dir / "cpu.stat").unlink()
        self.assertIsNone(host._slice_cpu_stat(slice_dir))

    def test_host_line_names_slice_cpu_gate(self):
        readings = {**READINGS, "slice_cpu_pressure": 12}
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(readings)}):
            self.assertEqual(run.host_status_line(),
                             "host: 8 cpus · ak cpu 12% · 4 G free · "
                             "a run is admitted while ≥ 3 G free and "
                             "ak cpu ≤ 40% · at most 1 run at once\n"
                             "heavy suites: 2 at once (derived)")


if __name__ == "__main__":
    unittest.main()
