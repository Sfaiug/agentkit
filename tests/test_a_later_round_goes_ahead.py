"""Finished work queues ahead of fresh launches, under the same host and count gates: a later
round, and an orchestrator's own PR waiting for its first review.

Offline: temporary state, fake process owners and injected host readings.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, record

HEALTHY = {"free_mb": 4096, "mem_total_mb": 16384, "cpus": 8, "load": 1,
           "slice_cpu_pressure": 5, "slice_memory_pressure": 0}
ROUND = {"started_at": 1, "round_summaries": [{"round": 1, "verdict": "FAIL"}]}
OWN_FIX = {"started_at": 2, "own_pr": True, "own_pr_wait": "reviewed-head"}
OWN_REVIEW = {"started_at": 3, "own_pr": True}
OWNER = {"pid": 999999, "process_identity": {"boot": "test", "ticks": 1}}


class LaterRoundGoesAhead(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-later-round-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "STATE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072"}))
        os.environ.pop("AK_MAX_LOAD", None)
        stack.enter_context(patch.object(record, "process_owner", return_value=OWNER))
        stack.enter_context(patch.object(record, "process_active", return_value=True))
        stack.enter_context(patch.object(gate, "landing_waits", return_value=False))
        # order, not pace: no poll's pause after each start
        stack.enter_context(patch.object(gate, "SLOT_POLL", 0))

    def queued(self, name, queued_at, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        record.save_state(directory, {
            "run_id": name, "state": "queued", "slot_waiting": True, "run_depth": 0,
            "queued_at": queued_at, "started_at": queued_at, "round_summaries": [],
            **OWNER, **extra})
        return directory

    def claim(self, directory, readings=HEALTHY):
        with gate.slot_lock():
            state = record.read_state(directory)
            admitted = gate.claim_slot(state, 1, readings)
            record.save_state(directory, state)
        return admitted

    def finish(self, directory):
        with record.record(directory) as state:
            state["state"] = "pass"

    def test_finished_work_is_admitted_first_in_queue_order_then_fresh_work(self):
        fresh = self.queued("fresh", 10)
        resumed = self.queued("round-two", 20, **ROUND)
        own = self.queued("own-fix", 30, **OWN_FIX)
        review = self.queued("own-review", 35, **OWN_REVIEW)
        later = self.queued("another-fresh", 40)
        for directory in (resumed, own, review, fresh, later):
            for behind in (resumed, own, review, fresh, later):
                if record.read_state(behind)["state"] == "queued" and behind != directory:
                    self.assertFalse(self.claim(behind))
                    self.assertEqual(record.read_state(behind).get("slot_wait_kind"), "count")
            self.assertTrue(self.claim(directory))
            self.finish(directory)

    def test_a_waiting_own_fix_queued_earlier_goes_before_a_finished_round(self):
        fresh = self.queued("fresh", 10)
        own = self.queued("own-fix", 20, **OWN_FIX)
        resumed = self.queued("round-two", 30, **ROUND)
        self.assertFalse(self.claim(resumed))
        self.assertTrue(self.claim(own))
        self.assertFalse(self.claim(fresh))

    def test_a_round_budget_or_a_wait_on_someone_elses_pr_does_not_jump_the_queue(self):
        fresh = self.queued("fresh", 10)
        for index, extra in enumerate(({"rounds": 3}, {"own_pr": False, "review_pr": "pr"},
                                      {**OWN_FIX, "own_pr": False}), 20):
            with self.subTest(extra=extra):
                directory = self.queued(f"unreviewed-{index}", index, **extra)
                self.assertFalse(self.claim(directory))
                self.assertEqual(record.read_state(directory)["slot_wait_kind"], "count")
        self.assertTrue(self.claim(fresh))

    def test_host_gates_hold_finished_work_and_fresh_launches(self):
        fresh = self.queued("fresh", 10)
        resumed = self.queued("round-two", 20, **ROUND)
        own = self.queued("own-fix", 30, **OWN_FIX)
        for readings, kind, env in (
                ({**HEALTHY, "load": 41}, "load", {"AK_MAX_LOAD": "8"}),
                ({**HEALTHY, "free_mb": 1024}, "memory", {}),
                ({**HEALTHY, "slice_memory_pressure": 60}, "unit memory", {})):
            with self.subTest(kind=kind), patch.dict(os.environ, env):
                for directory in (resumed, own, fresh):
                    self.assertFalse(self.claim(directory, readings))
                    self.assertFalse(self.claim(directory, readings))
                self.assertEqual(record.read_state(resumed)["slot_wait_kind"], kind)
                # Each kind of finished work also faces the host gate at the head of the queue.
                self.finish(resumed)
                self.assertFalse(self.claim(own, readings))
                self.assertFalse(self.claim(own, readings))
                self.assertEqual(record.read_state(own)["slot_wait_kind"], kind)
                with record.record(resumed) as state:
                    state["state"] = "queued"

        busy = {**HEALTHY, "slice_cpu_pressure": 60, "load": 41}
        for index, env in enumerate(({}, {"AK_MAX_LOAD": "8"})):
            with self.subTest(env=env), patch.dict(os.environ, env):
                first = self.queued(f"repair-{index}", 40 + index, first=True)
                self.assertTrue(self.claim(first, busy))
                self.finish(first)

    def test_the_count_cap_holds_both_kinds_of_finished_work(self):
        holder = self.queued("holder", 1)
        with record.record(holder) as state:
            state["state"] = "running"
        for index, extra in enumerate((ROUND, OWN_FIX, OWN_REVIEW), 20):
            with self.subTest(extra=extra):
                directory = self.queued(f"carried-{index}", index, **extra)
                self.assertFalse(self.claim(directory))
                self.assertFalse(self.claim(directory))
                self.assertEqual(record.read_state(directory)["slot_wait_kind"], "count")
                self.assertIn("limit full (1 running)", gate.slot_note(record.read_state(directory)))
                self.finish(directory)
        first = self.queued("repair", 40, first=True)
        self.assertTrue(self.claim(first))


if __name__ == "__main__":
    unittest.main()
