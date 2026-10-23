"""Admission and its wait count take seats in turn within each existing priority.

Offline: temporary state, invented seats, fake processes and healthy host readings.
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
from agentkit import config, gate, host, record  # noqa: E402

READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "cpus": 8, "load": 1,
            "slice_cpu_pressure": 5}


class AdmissionSeatsInTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seat-turns-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "STATE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        config.RUNS.mkdir(parents=True)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072"}))
        os.environ.pop("AK_MAX_LOAD", None)
        stack.enter_context(patch.object(host, "host_readings", return_value=READINGS))
        stack.enter_context(patch.object(record, "process_owner", return_value={"pid": 1}))
        stack.enter_context(patch.object(record, "process_active",
                                        side_effect=lambda state: state.get("pid") == 1))

    def queued(self, name, queued_at, seat=None, **extra):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "state": "queued", "slot_waiting": True,
                 "run_depth": 0, "queued_at": queued_at, **extra}
        if seat is not None:
            state["launched_session"] = seat
        record.save_state(directory, state)
        return name

    def state(self, name):
        return record.read_state(config.RUNS / name)

    def claim(self, name):
        with gate.slot_lock():
            state = self.state(name)
            admitted = gate.claim_slot(state, 1)
            record.save_state(config.RUNS / name, state)
        return admitted

    def assert_order(self, expected):
        for ahead, name in enumerate(expected):
            running, place, others = gate.slot_counts(self.state(name))
            self.assertEqual((running, place), (0, ahead), name)
            self.assertEqual(others[:place] + [name] + others[place:], expected)

    def backlog(self):
        for number in range(1, 4):
            self.queued(f"acme-{number}", number, "acme")
        self.queued("fix-api-1", 4, "fix-api")
        return ["acme-1", "fix-api-1", "acme-2", "acme-3"]

    def test_firsts_before_seconds_and_the_display_counts_the_same_order(self):
        expected = self.backlog()
        self.assert_order(expected)
        line = "waiting for a slot · 1 ahead"
        self.assertEqual(gate.slot_note(self.state("fix-api-1")), line)
        self.assertFalse(self.claim("fix-api-1"))
        self.assertEqual(self.state("fix-api-1")["slot_wait_reason"], line)
        self.assertEqual(gate.slot_note(self.state("fix-api-1")), line)
        self.assertEqual(gate.slot_queue()[2], expected)

    def test_turns_survive_admissions_even_when_each_run_finishes_immediately(self):
        pending = self.backlog()
        expected = list(pending)
        admitted = []
        while pending:
            self.assert_order(expected[len(admitted):])
            # Every waiter polls, with the busy seat's runs polling before the other seat.
            entered = []
            for _ in range(2):
                for name in sorted(pending):
                    if self.state(name)["state"] == "queued" and self.claim(name):
                        entered.append(name)
            self.assertEqual(len(entered), 1)
            name = entered[0]
            admitted.append(name)
            pending.remove(name)
            state = self.state(name)
            state["state"] = "pass"
            record.save_state(config.RUNS / name, state)
        self.assertEqual(admitted, expected)
        self.assertEqual(gate.slot_queue()[5], {})

    def test_each_rank_is_fifo_and_restarts_keep_their_first_queue_time(self):
        self.queued("acme-2", 5, "acme")
        self.queued("acme-1", 100, "acme", first_queued_at=2)
        self.queued("fix-api-2", 6, "fix-api")
        self.queued("fix-api-1", 1, "fix-api")
        self.queued("docs-2", 7, "docs")
        self.queued("docs-1", 3, "docs")
        self.assert_order(["fix-api-1", "acme-1", "docs-1",
                           "acme-2", "fix-api-2", "docs-2"])

    def test_runs_without_a_seat_each_have_their_own_turn(self):
        self.queued("solo-1", 1)
        self.queued("solo-2", 2, "")
        self.queued("acme-1", 3, "acme")
        self.queued("acme-2", 4, "acme")
        self.queued("fix-api-1", 5, "solo-1")
        self.assert_order(["solo-1", "solo-2", "acme-1", "fix-api-1", "acme-2"])

    def test_priority_flags_stay_ahead_and_turns_are_separate_for_each_priority(self):
        for kind, flags in (("fresh", {}), ("round", {"round_summaries": [{}]}),
                            ("fix", {"waiting_on": {"fix": {}}}),
                            ("green", {"waiting_on": {"land": "tree"}})):
            self.queued(f"{kind}-acme-1", 1, "acme", **flags)
            self.queued(f"{kind}-acme-2", 2, "acme", **flags)
            self.queued(f"{kind}-fix-api-1", 3, "fix-api", **flags)
        self.queued("first", 4, "docs", first=True)
        self.queued("own-pr", 4, "fix-api", own_pr=True, own_pr_wait=True)
        expected = ["green-acme-1", "green-fix-api-1", "green-acme-2",
                    "fix-acme-1", "fix-fix-api-1", "first", "fix-acme-2",
                    "round-acme-1", "round-fix-api-1", "round-acme-2", "own-pr",
                    "fresh-acme-1", "fresh-fix-api-1", "fresh-acme-2"]
        self.assert_order(expected)

    def test_a_green_delivery_queued_last_still_goes_first(self):
        expected = self.backlog()
        self.assertFalse(self.claim("fix-api-1"))
        green = self.queued("green", 10, "acme", waiting_on={"land": "tree"})
        self.assert_order([green, *expected])
        self.assertTrue(self.claim(green))
        self.assertEqual(gate.slot_queue()[2], expected)


if __name__ == "__main__":
    unittest.main()
