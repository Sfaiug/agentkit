"""Host resource admission is conservative, FIFO, and counts what runs let in may still take;
with nothing measured, a run waits a poll behind the last let in."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, handback, history, host, run  # noqa: E402
from agentkit import record


HEALTHY = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
           "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}


class Slots(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                           "AK_MAX_LOAD": "8"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.owner = patch.object(record, "process_owner", return_value={"pid": 1})
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.counts = patch.object(gate, "slot_counts", return_value=(0, 0, []))
        self.counts.start()
        self.addCleanup(self.counts.stop)
        self.held = patch.object(gate, "frozen_runs", return_value=0)
        self.held.start()
        self.addCleanup(self.held.stop)
        # claim_slot leaves the queue it decided beside the runs
        temp = tempfile.TemporaryDirectory(prefix=".ak-test-slots-", dir=REPO)
        self.addCleanup(temp.cleanup)
        runs = patch.object(config, "RUNS", Path(temp.name))
        runs.start()
        self.addCleanup(runs.stop)
        home = patch.object(config, "HOME", Path(temp.name))
        home.start()
        self.addCleanup(home.stop)

    def claim(self, readings, state=None):
        state = {"run_id": "r", "run_depth": 0, **(state or {})}
        with patch.object(host, "host_readings", return_value=readings):
            return gate.claim_slot(state, 1), state

    def test_memory_low_waits_then_admits_once_healthy(self):
        state = {"run_id": "r", "run_depth": 0}
        low = {**HEALTHY, "free_mb": 1024}
        with patch.object(host, "host_readings", side_effect=[low, HEALTHY]):
            self.assertFalse(gate.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_reason"], "waiting for memory · 1 G free, needs 3 G")
            self.assertTrue(gate.claim_slot(state, 1))
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
        with patch.object(host, "host_readings", side_effect=AssertionError("must not read")):
            self.assertTrue(gate.claim_slot(state, 1))

    def test_fifo_waiter_cannot_overtake(self):
        state = {"run_id": "behind", "run_depth": 0}
        with patch.object(gate, "slot_counts", return_value=(0, 1, [])), \
                patch.object(host, "host_readings", side_effect=AssertionError("must not read")):
            self.assertFalse(gate.claim_slot(state, 1))
        self.assertEqual(state["slot_wait_kind"], "count")

    def test_zero_max_runs_disables_all_gates(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MAX_RUNS": "0"}), \
                patch.object(host, "host_readings", side_effect=AssertionError("must not read")):
            self.assertTrue(gate.claim_slot(state, 1))

    def test_zero_minimum_disables_memory_gate(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "0", "AK_MAX_LOAD": "8"}), \
                patch.object(host, "host_readings", return_value={**HEALTHY, "free_mb": 0}):
            self.assertTrue(gate.claim_slot(state, 1))

    def test_zero_maximum_disables_load_gate(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "0"}), \
                patch.object(host, "host_readings", return_value={**HEALTHY, "load": 400}):
            self.assertTrue(gate.claim_slot(state, 1))

    def test_unknown_readings_fail_open(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.object(host, "host_readings", return_value={}):
            self.assertTrue(gate.claim_slot(state, 1))
        self.assertEqual(state["state"], "running")

    def test_a_run_let_in_holds_the_next_a_poll_naming_steadiness(self):
        state = {"run_id": "r", "run_depth": 0}
        with patch.object(host, "host_readings", return_value=HEALTHY):
            self.assertTrue(gate.claim_slot({"run_id": "other", "run_depth": 0}, 1))
            self.assertFalse(gate.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_reason"],
                             "waiting for steady readings · 4 G free, load 1")
            self.assertNotIn("slot_wait_kind", state)
            later = time.time() + gate.SLOT_POLL
            with patch.object(gate, "time", Mock(time=lambda: later)):
                self.assertTrue(gate.claim_slot(state, 1))
        self.assertEqual(state["state"], "running")

    def test_what_runs_let_in_may_still_take_holds_in_place_of_a_poll_and_says_so(self):
        roomy = {**HEALTHY, "free_mb": 8192, "unit_memory_high_mb": 16384}
        with patch.object(history, "recent_peak_rss_mb", return_value=2048), \
                patch.object(history, "peaks_so_far", return_value={"other": 512}), \
                patch.object(gate, "_holders", return_value=[{"run_id": "other"}]):
            self.assertTrue(self.claim(roomy, {"run_id": "other"})[0])
            self.assertTrue(self.claim(roomy)[0])
            for readings, reason, kind in (
                    ({**roomy, "free_mb": 4096}, "waiting for memory · 4 G free, 1 starting run "
                     "may take 1.5 G more, needs 3 G", "memory"),
                    ({**roomy, "unit_memory_high_mb": 3000}, "waiting for the unit's memory · "
                     "2.8 G left, 1 starting run may take 1.5 G more, a run needs 2 G",
                     "unit memory")):
                admitted, state = self.claim(readings)
                self.assertFalse(admitted)
                self.assertEqual((state["slot_wait_reason"], state["slot_wait_kind"]),
                                 (reason, kind))

    def test_admission_clears_wait_reason(self):
        state = {"run_id": "r", "run_depth": 0}
        low = {**HEALTHY, "free_mb": 1024}
        with patch.object(host, "host_readings", side_effect=[low, HEALTHY]):
            self.assertFalse(gate.claim_slot(state, 1))
            self.assertEqual(state["slot_wait_kind"], "memory")
            self.assertTrue(gate.claim_slot(state, 1))
        self.assertNotIn("slot_wait_reason", state)
        self.assertNotIn("slot_wait_kind", state)

    def test_disabled_gates_render_as_off(self):
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "0", "AK_MAX_LOAD": "0"}), \
                patch.object(host, "host_readings", return_value=HEALTHY), \
                patch.object(gate, "_heavy_running", return_value=0), \
                patch.object(config, "max_gates", return_value=None):
            self.assertEqual(gate.host_status_line(),
                             "host: 8 cpus · load 1 · 4 G free · "
                             "a run is admitted (host memory and load gates off)"
                             " · at most 1 run at once\nheavy suites: 2 at once (derived)")
        with patch.dict(os.environ, {"AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "0"}), \
                patch.object(host, "host_readings", return_value=HEALTHY), \
                patch.object(gate, "_heavy_running", return_value=0), \
                patch.object(config, "max_gates", return_value=None):
            self.assertEqual(gate.host_status_line(),
                             "host: 8 cpus · load 1 · 4 G free · "
                             "a run is admitted while ≥ 3 G free · at most 1 run at once\n"
                             "heavy suites: 2 at once (derived)")

    def test_a_launch_lets_no_run_in(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-slots-", dir=REPO) as temp:
            runs = Path(temp) / "runs"
            runs.mkdir()
            with patch.object(config, "RUNS", runs), \
                    patch.object(host, "host_readings", return_value=HEALTHY), \
                    patch.object(run, "history_start"), \
                    patch.object(run, "redress_seat"), patch.object(handback, "redress_seat"), \
                    patch.dict(os.environ, {"AGENTKIT_SESSION": "",
                                            "AK_RUN_DEPTH": "0"}):
                directory = runs / "r"
                directory.mkdir()
                run.capture_launch(directory)
                state = record.read_state(directory)
                # the process that waits owns the start
                self.assertEqual(state["state"], "queued")

    def test_wait_log_names_memory_reason(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-slots-", dir=REPO) as temp:
            root = Path(temp)
            runs = root / "runs"
            runs.mkdir()
            with patch.object(config, "RUNS", runs), patch.object(config, "HOME", root), \
                    patch.object(gate, "SLOT_POLL", .001), \
                    patch.object(gate, "slot_counts", return_value=(0, 0, [])), \
                    patch.object(host, "host_readings",
                                 side_effect=[{**HEALTHY, "free_mb": 1024}, HEALTHY, HEALTHY]), \
                    patch.object(run, "redress_seat"), patch.object(handback, "redress_seat"):
                directory = runs / "r"
                directory.mkdir()
                (directory / "log.txt").write_text("started\n")
                history.start_run("r", repo="/home/fixture/code/acme")
                record.save_state(directory, {"run_id": "r", "state": "queued",
                                            "slot_waiting": True, "queued_at": time.time(),
                                            "pid": os.getpid(), "run_depth": 0})
                gate.wait_for_slot(directory)
                content = (directory / "log.txt").read_text()
                self.assertRegex(content.splitlines()[0],
                                 r"^waited \d+ min for a slot \(memory\)$")
                # the history row keeps the wait its waiter counted
                self.assertGreater(history.get("r")["slot_wait_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
