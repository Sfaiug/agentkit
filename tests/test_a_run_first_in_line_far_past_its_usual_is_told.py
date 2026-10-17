"""The run first in line for a slot that has waited there far past the runs first before it is a
stall: the tick tells the `audit` seat once, as it tells a landing line's pass far past its usual.
Admission keeps how long each run first in line waited there.

Offline: a temporary HOME holding the shipped default config, run records written by hand, the
clock and the host's gates injected, and the seat finder, opener and typer faked; nothing starts
a seat, a run or tmux.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import audit, config, gate, land, orch, record, stuck, watch

NOW = 1_800_000_000.0
LIVE = record.process_owner()
GONE = {"pid": 2 ** 22 + 1, "process_identity": {"boot": "gone", "ticks": 0}}
STOPPED = {"state": "stopped", "slot_waiting": False}     # its owner, a job's scheduler, lives on


class FirstInLineFarPastItsUsual(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stuck-first-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "1", "NO_COLOR": "1"}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV"):
            stack.enter_context(patch.object(config, name, self.root / ".agentkit" / name.lower()))
        stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        config.ensure_dirs()
        self.cfg = config.load()
        self.log = []
        stack.enter_context(patch.object(watch, "seat_closed_by_owner", return_value=False))
        stack.enter_context(patch.object(orch, "find", return_value={"name": "audit", "created": 7}))
        stack.enter_context(patch.object(orch, "records", return_value={}))
        stack.enter_context(patch.object(orch, "ensure", return_value=True))
        self.typed = stack.enter_context(patch.object(watch, "type_at_prompt", return_value=True))
        audit.write({"week": audit.week_of(NOW), "line": "the week's", "delivered": NOW - 60})
        self.clock = NOW
        stack.enter_context(patch.object(gate, "time", SimpleNamespace(time=lambda: self.clock)))
        stack.enter_context(patch.object(gate, "SLOT_POLL", 30))
        # the host's gates hold the runs named here and let every other run in
        self.held = set()
        stack.enter_context(patch.object(gate, "_host_admits",
                                         lambda state, _readings, _first: state["run_id"] not in
                                         self.held))

    def queue(self, name, at):
        run_dir = config.RUNS / name
        run_dir.mkdir()
        state = {"run_id": name, "state": "queued", "slot_waiting": True, "queued_at": at,
                 "run_depth": 0, **LIVE}
        record.save_state(run_dir, state)
        return state

    def poll(self, state, at):
        """The waiting run's poll at `at`, with no count cap: whether it was let in."""
        self.clock = at
        admitted = gate.claim_slot(state, 0)
        record.save_state(config.RUNS / state["run_id"], state)
        return admitted

    def firsts(self, waits):
        """Runs first in line one after another, each let in after its wait there."""
        at = NOW - 20_000
        for index, wait in enumerate(waits):
            state = self.queue(f"20270115-08{index:02d}-acme-earlier", at)
            self.held.add(state["run_id"])
            self.poll(state, at)
            self.held.discard(state["run_id"])
            self.assertTrue(self.poll(state, at + wait))
            at += wait + 1

    def tick(self, now=NOW):
        watch.tell_audit(self.cfg, self.log.append, now)
        return [call.args[1] for call in self.typed.call_args_list]

    def test_a_run_first_in_line_far_past_the_usual_is_told_to_the_audit_seat_once(self):
        self.firsts((60, 60, 60))
        first = self.queue("20270115-0900-fix-api", NOW - 3000)
        behind = self.queue("20270115-0901-fix-web", NOW - 2000)
        self.held |= {first["run_id"], behind["run_id"]}
        self.poll(first, NOW - 3000)
        self.assertFalse(self.poll(behind, NOW - 2000))
        self.poll(first, NOW - 10)
        self.assertEqual(self.tick(), [
            "ak stalled: 20270115-0900-fix-api has been first in line for a slot for 50m, more "
            "than 3 times the usual 1m, with 1 behind it; `ak run status` shows what it waits "
            "on. Find why and build the smallest change to ak that keeps it from happening "
            "again, through the line, and ak notify done once it is live."])
        self.assertEqual(self.log[-1], "audit: told the audit seat about the stall of the slot "
                                       "queue")
        # another stall told while the first goes unpolled, its owner gone, leaves it told
        record.save_state(config.RUNS / first["run_id"], {**first, **GONE})
        land._keep_passes(config.RUNS / ".merge-acme.lock",
                          {"started": NOW - 3000, "took": [60, 60, 60], **LIVE})
        self.assertEqual(len(self.tick(NOW + 600)), 2)
        self.poll(first, NOW + 650)     # recovered: a new owner waits on in its place
        self.assertEqual(len(self.tick(NOW + 660)), 2)
        # let in, it hands first place on: the next run's wait there starts from naught
        self.held.discard(first["run_id"])
        self.assertTrue(self.poll(first, NOW + 700))
        self.poll(behind, NOW + 710)
        self.assertEqual(len(self.tick(NOW + 720)), 2)

    def test_a_first_within_the_usual_or_waiting_no_more_is_no_stall(self):
        for waits, since, end in (((60, 60, 60), NOW - 1700, {}),     # under half an hour
                                  ((700, 700, 700), NOW - 2000, {}),  # under 3 times 700s
                                  ((60, 60, 60), NOW - 3000, STOPPED),  # it waits no more
                                  ((60, 60), NOW - 3000, {})):        # no pace yet
            with self.subTest(waits=waits, since=since, end=end):
                shutil.rmtree(config.RUNS)
                config.ensure_dirs()
                self.firsts(waits)
                first = self.queue("20270115-0900-fix-api", since)
                self.held.add(first["run_id"])
                self.poll(first, since)
                self.poll(first, NOW - 10)
                record.save_state(config.RUNS / first["run_id"], {**first, **end})
                self.assertEqual(self.tick(), [])
                self.assertEqual(stuck.read(), {})


if __name__ == "__main__":
    unittest.main()
