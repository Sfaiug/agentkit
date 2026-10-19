"""A landing line's check pass that runs far past its line's usual is a stall: the tick tells the
`audit` seat once, after the week's line, so ak repairs itself without the owner.  Each lander
keeps the time of its passes that checked something.

Offline: a temporary HOME holding the shipped default config, line records written by hand, and
the seat finder, opener and typer faked; nothing starts a seat, a lander or tmux.
"""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import audit, config, deliver, land, orch, record, stuck, watch

NOW = 1_800_000_000.0
LIVE = record.process_owner()
GONE = {"pid": 2 ** 22 + 1, "process_identity": {"boot": "gone", "ticks": 0}}


class PassFarPastItsUsual(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stuck-pass-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "NO_COLOR": "1"}))
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
        self.turn = deliver.merge_lock_path("https://github.com/acme/widget", "main")
        member = config.RUNS / "20270115-0900-fix-api"
        member.mkdir()
        # written as it stands, not saved: a save starts the line's lander
        (member / "run.json").write_text(json.dumps({
            "run_id": member.name, "state": "waiting", "repo": str(self.root / "code" / "acme"),
            "waiting_on": {"line": self.turn.name, "joined": NOW - 7200}}))

    def passes(self, started, owner=LIVE, took=(600, 700, 800)):
        land._keep_passes(self.turn, {"took": list(took), "started": started, **owner})

    def tick(self, now=NOW):
        watch.tell_audit(self.cfg, self.log.append, now)
        return [call.args[1] for call in self.typed.call_args_list]

    def test_a_pass_far_past_its_line_s_usual_is_told_to_the_audit_seat_once(self):
        self.passes(NOW - 3000)
        self.assertEqual(self.tick(), [
            "ak stalled: the acme landing line has run one check pass for 50m, more than 3 times "
            f"its usual 11m, with 1 in line; its log is {self.turn.with_suffix('.log')}. Find why "
            "and build the smallest change to ak that keeps it from happening again, through the "
            "line."])
        self.assertEqual(self.log[-1], "audit: told the audit seat about the stall of the acme "
                                       "landing line")
        self.assertEqual(len(self.tick(NOW + 600)), 1)

    def test_a_pass_within_its_usual_or_with_no_live_lander_or_pace_is_no_stall(self):
        for started, owner, took in ((NOW - 1700, LIVE, (60, 60, 60)),     # under half an hour
                                     (NOW - 2000, LIVE, (700, 700, 700)),  # under 3 times 700s
                                     (NOW - 3000, GONE, (600, 700, 800)),  # its lander is gone
                                     (NOW - 3000, LIVE, (600, 700)),       # no pace yet
                                     (None, {}, (600, 700, 800))):         # no pass running
            with self.subTest(started=started, took=took):
                self.passes(started, owner, took)
                self.assertEqual(self.tick(), [])
                self.assertEqual(stuck.read(), {})

    def test_the_week_s_line_goes_first(self):
        audit.write({"week": audit.week_of(NOW), "line": "the week's", "delivered": None})
        self.passes(NOW - 3000)
        self.assertEqual(self.tick(), ["the week's"])
        self.assertEqual(stuck.read(), {})
        self.assertIn("ak stalled: the acme landing line", self.tick(NOW + 60)[-1])

    def test_a_stall_s_line_waiting_for_its_enter_is_sent_before_a_new_week_s(self):
        def typed(_seat, line, _log, typed=None, receipt=None, **_kw):
            if typed is None:
                receipt({"line": line})     # in the composer, and its Enter failed
            return typed is not None
        self.typed.side_effect = typed
        self.passes(NOW - 3000)
        stall, week = self.tick()[-1], NOW + 7 * 86400
        self.assertEqual(self.tick(week)[-1], stall)
        self.assertEqual((stuck.read()["delivered"], audit.read()["week"]),
                         (week, audit.week_of(NOW)))
        self.assertIn(f"ak's week {audit.week_of(week)}", self.tick(week)[-1])

    def test_a_running_stall_is_told_once_however_many_others_are_told_meanwhile(self):
        self.passes(NOW - 3000)
        self.tick()
        for index in range(20):
            other = deliver.merge_lock_path(f"https://github.com/acme/api-{index}", "main")
            land._keep_passes(other, {"took": [600, 700, 800], "started": NOW - 3000, **LIVE})
            self.tick(NOW + index)
            land._keep_passes(other, {"took": [600, 700, 800]})    # that pass ended
        told = self.tick(NOW + 60)
        self.assertEqual((len(told), sum("the acme landing line" in line for line in told)),
                         (21, 1))

    def test_a_lander_keeps_the_time_of_its_passes_that_checked_something(self):
        clock = [1000.0, 1120.0, 2000.0, 2005.0]
        with patch.object(land, "time", SimpleNamespace(time=lambda: clock.pop(0))):
            with land._pass(self.turn) as held:
                self.assertTrue(held)
                self.assertEqual(land.passes(self.turn), {"took": [], "started": 1000.0, **LIVE})
            self.assertEqual(land.passes(self.turn), {"took": [120.0]})
            with land._pass(self.turn) as held:     # five seconds: it checked nothing
                self.assertTrue(held)
            self.assertEqual(land.passes(self.turn), {"took": [120.0]})
            with self.turn.with_suffix(".lander.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with land._pass(self.turn) as held:     # another lander's pass is running
                    self.assertFalse(held)
            self.assertEqual(land.passes(self.turn), {"took": [120.0]})


if __name__ == "__main__":
    unittest.main()
