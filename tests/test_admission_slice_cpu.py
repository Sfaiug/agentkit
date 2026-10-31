"""Admission gates no CPU unless the owner pinned max_load.

A run starts whatever the host load or the runs slice's CPU pressure is; a pinned
max_load restores the old host-load check. Offline: a throwaway HOME, mocked slot
counts, and injected host readings. The real machine's load, pressure and cgroups
are never read.
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
from agentkit import gate, host, config  # noqa: E402
from agentkit import record

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
        config.RUNS.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": "1",
                                                         "AK_MIN_FREE_MB": "3072"}))
        os.environ.pop("AK_MAX_LOAD", None)
        self.stack.enter_context(patch.object(gate, "slot_counts", return_value=(0, 0, [])))
        self.stack.enter_context(patch.object(gate, "frozen_runs", return_value=0))
        self.stack.enter_context(patch.object(record, "process_owner",
                                              return_value={"pid": 1}))

    def claim(self, readings, state=None):
        state = {"run_id": "r", "run_depth": 0, **(state or {})}
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(readings)}):
            return gate.claim_slot(state, 1), state

    def test_high_host_load_and_slice_pressure_admit(self):
        loaded = {**READINGS, "load": 41, "slice_cpu_pressure": 90}
        admitted, state = self.claim(loaded)
        self.assertTrue(admitted)
        self.assertEqual(state["state"], "running")

    def test_memory_floor_still_gates(self):
        admitted, state = self.claim({**READINGS, "free_mb": 1024,
                                      "slice_cpu_pressure": 5})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_kind"], "memory")

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
        self.assertTrue(admitted)
        self.assertEqual(state["state"], "running")

    def test_slice_pressure_reads_the_larger_of_some_avg10_and_avg60(self):
        slice_dir = self.root / "agentkit.slice"
        slice_dir.mkdir()
        (slice_dir / "cpu.pressure").write_text(
            "some avg10=24.01 avg60=32.25 avg300=41.39 total=115793455101\n"
            "full avg10=2.73 avg60=3.79 avg300=5.51 total=30965092215\n")
        self.assertEqual(host._slice_pressure(slice_dir, "cpu"), 32.25)
        (slice_dir / "cpu.pressure").unlink()
        self.assertIsNone(host._slice_pressure(slice_dir, "cpu"))
        (slice_dir / "cpu.pressure").write_text("some avg10=banana\n")
        self.assertIsNone(host._slice_pressure(slice_dir, "cpu"))

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

    def test_host_line_names_only_the_gates(self):
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(READINGS)}):
            self.assertEqual(gate.host_status_line(),
                             "host: 8 cpus · 4 G free · "
                             "a run is admitted while ≥ 3 G free · at most 1 run at once\n"
                             "heavy suites: 2 at once (derived)")
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(READINGS),
                                     "AK_MAX_LOAD": "8"}):
            self.assertEqual(gate.host_status_line().splitlines()[0],
                             "host: 8 cpus · load 1 · 4 G free · "
                             "a run is admitted while ≥ 3 G free and load ≤ 8 · at most 1 run at once")


if __name__ == "__main__":
    unittest.main()
