"""Host resource admission is conservative, FIFO and steady across two polls."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run  # noqa: E402


HEALTHY = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
           "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}


class Slots(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                           "AK_MAX_LOAD": "8"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.owner = patch.object(run, "process_owner", return_value={"pid": 1})
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.counts = patch.object(run, "slot_counts", return_value=(0, 0))
        self.counts.start()
        self.addCleanup(self.counts.stop)
        self.held = patch.object(run, "frozen_runs", return_value=0)
        self.held.start()
        self.addCleanup(self.held.stop)

    def claim(self, readings, state=None):
        state = {"run_id": "r", "run_depth": 0, **(state or {})}
        with patch.object(run, "host_readings", return_value=readings):
            return run.claim_slot(state, 1), state

    def test_memory_low_waits_then_admits_after_two_healthy_polls(self):
        state = {"run_id": "r", "run_depth": 0}
        low = {**HEALTHY, "free_mb": 1024}
        with patch.object(run, "host_readings", side_effect=[low, HEALTHY, HEALTHY]):
            self.assertFalse(run.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_reason"], "waiting for memory · 1 G free, needs 3 G")
            self.assertFalse(run.claim_slot(state, 1))
            self.assertTrue(run.claim_slot(state, 1))
        self.assertEqual(state["state"], "running")

    def test_high_load_explains_wait(self):
        admitted, state = self.claim({**HEALTHY, "load": 41})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_reason"], "waiting for the host to calm · load 41, limit 8")

    def test_unit_memory_ceiling_explains_wait(self):
        admitted, state = self.claim({**HEALTHY, "unit_memory_current_mb": 901,
                                      "unit_memory_high_mb": 1000})
        self.assertFalse(admitted)
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for the unit's memory · 0.9 of 1 G")

    def test_depth_one_is_never_host_gated(self):
        state = {"run_id": "worker", "run_depth": 1}
        with patch.object(run, "host_readings", side_effect=AssertionError("must not read")):
            self.assertTrue(run.claim_slot(state, 1))

    def test_fifo_waiter_cannot_overtake(self):
        state = {"run_id": "behind", "run_depth": 0}
        with patch.object(run, "slot_counts", return_value=(0, 1)), \
                patch.object(run, "host_readings", side_effect=AssertionError("must not read")):
            self.assertFalse(run.claim_slot(state, 1))
        self.assertEqual(state["slot_wait_kind"], "count")

    def test_zero_max_runs_disables_all_gates(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MAX_RUNS": "0"}), \
                patch.object(run, "host_readings", side_effect=AssertionError("must not read")):
            self.assertTrue(run.claim_slot(state, 1))

    def test_zero_minimum_disables_memory_gate(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "0", "AK_MAX_LOAD": "8"}), \
                patch.object(run, "host_readings", return_value={**HEALTHY, "free_mb": 0}):
            self.assertFalse(run.claim_slot(state, 1))  # first steady poll
            self.assertTrue(run.claim_slot(state, 1))

    def test_zero_maximum_disables_load_gate(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "0"}), \
                patch.object(run, "host_readings", return_value={**HEALTHY, "load": 400}):
            self.assertFalse(run.claim_slot(state, 1))  # first steady poll
            self.assertTrue(run.claim_slot(state, 1))

    def test_unknown_readings_fail_open(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.object(run, "host_readings", return_value={}):
            self.assertFalse(run.claim_slot(state, 1))  # first steady poll
            self.assertTrue(run.claim_slot(state, 1))
        self.assertEqual(state["state"], "running")

    def test_healthy_first_poll_names_steadiness(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.object(run, "host_readings", return_value=HEALTHY):
            self.assertFalse(run.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_reason"],
                             "waiting for steady readings · 4 G free, load 1")
            self.assertNotIn("slot_wait_kind", state)
            self.assertTrue(run.claim_slot(state, 1))
        self.assertEqual(state["state"], "running")

    def test_admission_clears_wait_reason(self):
        state = {"run_id": "r", "run_depth": 0}
        low = {**HEALTHY, "free_mb": 1024}
        with patch.object(run, "host_readings", side_effect=[low, HEALTHY, HEALTHY]):
            self.assertFalse(run.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_kind"], "memory")
            self.assertFalse(run.claim_slot(state, 1))
            self.assertTrue(run.claim_slot(state, 1))
        self.assertNotIn("slot_wait_reason", state)
        self.assertNotIn("slot_wait_kind", state)

    def test_disabled_gates_render_as_off(self):
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "0", "AK_MAX_LOAD": "0"}), \
                patch.object(run, "host_readings", return_value=HEALTHY):
            self.assertEqual(run.host_status_line(),
                             "host: 8 cpus · load 1 · 4 G free · "
                             "a run is admitted (host memory and load gates off)"
                             " · at most 1 run at once")
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "0"}), \
                patch.object(run, "host_readings", return_value=HEALTHY):
            self.assertEqual(run.host_status_line(),
                             "host: 8 cpus · load 1 · 4 G free · "
                             "a run is admitted while ≥ 3 G free · at most 1 run at once")

    def test_capture_banks_no_healthy_poll(self):
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            runs = Path(temp) / "runs"
            runs.mkdir()
            with patch.object(config, "RUNS", runs), \
                    patch.object(run, "host_readings", return_value=HEALTHY), \
                    patch.object(run, "history_start"), \
                    patch.object(run, "refresh_seat_tally"), \
                    patch.dict(os.environ, {"AGENTKIT_SESSION": "",
                                            "AK_RUN_DEPTH": "0"}):
                directory = runs / "r"
                directory.mkdir()
                run.capture_launch(directory)
                state = run.read_state(directory)
                self.assertEqual(state["state"], "queued")
                self.assertNotIn("slot_healthy_polls", state)

    def test_wait_log_names_memory_reason(self):
        with tempfile.TemporaryDirectory(dir=REPO) as temp:
            root = Path(temp)
            runs = root / "runs"
            runs.mkdir()
            with patch.object(config, "RUNS", runs), patch.object(run, "SLOT_POLL", .001), \
                    patch.object(run, "slot_counts", return_value=(0, 0)), \
                    patch.object(run, "host_readings",
                                 side_effect=[{**HEALTHY, "free_mb": 1024}, HEALTHY, HEALTHY]), \
                    patch.object(run, "refresh_seat_tally"):
                directory = runs / "r"
                directory.mkdir()
                (directory / "log.txt").write_text("started\n")
                run.save_state(directory, {"run_id": "r", "state": "queued",
                                            "slot_waiting": True, "queued_at": time.time(),
                                            "pid": os.getpid(), "run_depth": 0})
                run.wait_for_slot(directory)
                content = (directory / "log.txt").read_text()
                self.assertRegex(content.splitlines()[0],
                                 r"^waited \d+ min for a slot \(memory\)$")


if __name__ == "__main__":
    unittest.main()
