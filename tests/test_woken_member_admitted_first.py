"""Lander verdicts admit woken members ahead of ordinary work, with land before fix."""

from contextlib import ExitStack, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, host, land, record, run

READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "cpus": 8, "load": 41,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000,
            "slice_cpu_pressure": 52}


class WokenMemberAdmission(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-woken-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, "HOME", self.root))
        self.stack.enter_context(patch.object(config, "RUNS", self.root / "runs"))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072"}))
        os.environ.pop("AK_MAX_LOAD", None)
        self.stack.enter_context(patch.object(record, "process_owner", return_value={
            "pid": os.getpid(), "process_identity": {"boot": "test", "ticks": 1}}))
        self.stack.enter_context(patch.object(
            record, "process_active", side_effect=lambda state: state.get("state") == "running"))
        self.stack.enter_context(patch.object(land, "start_line", return_value=False))
        self.stack.enter_context(patch.object(host, "host_readings", return_value=READINGS))
        self.stack.enter_context(patch.object(run, "refresh_seat_tally"))

    def receipt(self, name, queued_at, verdict=None, word="queued"):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        state = {"run_id": name, "state": word, "run_depth": 0,
                 "started_at": queued_at, "queued_at": queued_at,
                 "slot_waiting": word == "queued", "verdict": None,
                 **record.process_owner()}
        if verdict:
            state["waiting_on"] = {"line": "land-acme.lock", "joined": 1,
                                   verdict: "tree" if verdict == "land" else
                                   {"line": "suite failed", "log": "lander.log"}}
            if word == "queued":
                state["resume_from"] = "waiting"
        record.save_state(directory, state)
        (directory / "log.txt").touch()
        return directory

    def claim(self, directory, limit=1, readings=READINGS):
        with run.slot_lock():
            state = record.read_state(directory)
            admitted = run.claim_slot(state, limit, readings)
            record.save_state(directory, state)
        return admitted

    def test_woken_members_pass_queue_count_cap_and_cpu_gate(self):
        self.receipt("holder", 1, word="running")
        ordinary = self.receipt("ordinary", 10)
        later = self.receipt("later", 20)
        self.assertFalse(self.claim(ordinary, limit=0))
        self.assertEqual(record.read_state(ordinary)["slot_wait_kind"], "cpu")
        self.assertFalse(self.claim(later, limit=0))
        self.assertEqual(record.read_state(later)["slot_wait_kind"], "count")

        for verdict in ("land", "fix"):
            with self.subTest(verdict=verdict):
                directory = self.receipt(verdict, 30, verdict, word="waiting")
                waiting = record.read_state(directory)["waiting_on"]
                # A broken priority must fail instead of polling forever.
                with redirect_stdout(StringIO()), patch.object(
                        run.time, "sleep", side_effect=[None, AssertionError("not admitted")]):
                    state = run.wait_for_slot(directory)
                self.assertEqual(state["state"], "running")
                self.assertGreater(state["queued_at"], 20)
                self.assertEqual(state["waiting_on"], waiting)
                self.assertNotIn("first", record.read_state(directory))
                self.assertFalse(self.claim(ordinary, limit=0))
                self.assertEqual(record.read_state(ordinary)["slot_wait_kind"], "cpu")

    def test_land_is_admitted_before_earlier_fix(self):
        self.receipt("holder", 1, word="running")
        fix = self.receipt("fix", 10, "fix")
        green = self.receipt("green", 20, "land")
        self.assertLess(run.slot_order(record.read_state(green)),
                        run.slot_order(record.read_state(fix)))
        self.assertEqual(run.slot_note(record.read_state(fix)), "waiting for a slot · 1 ahead")
        self.assertFalse(self.claim(fix))
        self.assertEqual(record.read_state(fix)["slot_wait_kind"], "count")
        self.assertFalse(self.claim(green))
        self.assertTrue(self.claim(green))
        self.assertFalse(self.claim(fix))
        self.assertTrue(self.claim(fix))

    def test_a_failed_pr_check_keeping_its_land_verdict_waits_behind_a_green_delivery(self):
        self.receipt("holder", 1, word="running")
        failed = self.receipt("failed-pr-check", 10, "land")
        with record.record(failed) as state:
            state["waiting_on"]["fix"] = {"line": "required checks failed: suite", "log": "pr.log"}
        green = self.receipt("green", 20, "land")
        self.assertLess(run.slot_order(record.read_state(green)),
                        run.slot_order(record.read_state(failed)))
        self.assertFalse(self.claim(green))
        self.assertTrue(self.claim(green))

    def test_memory_gates_still_hold_both_verdicts(self):
        for verdict in ("land", "fix"):
            with self.subTest(verdict=verdict), patch.dict(os.environ, {"AK_MAX_LOAD": "8"}):
                directory = self.receipt(verdict, 10, verdict)
                self.assertFalse(self.claim(directory, readings={**READINGS, "free_mb": 1024}))
                self.assertEqual(record.read_state(directory)["slot_wait_kind"], "memory")
                self.assertFalse(self.claim(directory, readings={
                    **READINGS, "unit_memory_current_mb": 901}))
                self.assertEqual(record.read_state(directory)["slot_wait_kind"], "unit memory")
                self.assertFalse(self.claim(directory))
                self.assertTrue(self.claim(directory))

    def test_consuming_verdict_removes_priority(self):
        ordinary = self.receipt("ordinary", 10)
        for verdict in ("land", "fix"):
            with self.subTest(verdict=verdict):
                directory = self.receipt(verdict, 20, verdict)
                state = record.read_state(directory)
                self.assertLess(run.slot_order(state), run.slot_order(record.read_state(ordinary)))
                state["waiting_on"].pop(verdict)
                record.save_state(directory, state)
                self.assertGreater(run.slot_order(state), run.slot_order(record.read_state(ordinary)))
                self.assertFalse(self.claim(directory))
                self.assertEqual(record.read_state(directory)["slot_wait_kind"], "count")


if __name__ == "__main__":
    unittest.main()
