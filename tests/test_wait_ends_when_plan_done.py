"""A seat's wait is over once its plan is done and its changes are live.

On 24 Oct 2026 a seat's last run merged and went live, finishing its plan, while its `ak wait`
named another seat's unrelated run: nothing woke it to write its final message, and the wait
kept it `working` for three days.  Now the tick's wait pass (`watch.wait_over`) also ends a wait
whose seat's own work is done and live (`watch.work_live`): one line at its quiet prompt, once,
held while a run of its own still waits on its live check or a plan line is open, and `ak wait`
from such a seat is refused.  The fixture is fixtures.seats: a temporary HOME, a fake tmux and
pane.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

from fixtures.seats import NOW, SEAT, SENDER, Seats
from agentkit import config, record, watch

REPO = Path(__file__).resolve().parents[1]
AK_MAIN = runpy.run_path(str(REPO / "bin/ak"))["main"]
THEIRS, MINE = "20261024-0900-fix-api", "20261024-0800-acme-docs"
OVER = "your wait is over. Decide the next step."


class WaitEndsWhenPlanDone(Seats):
    def setUp(self):
        super().setUp()
        config.plan_path(SEAT).write_text("- [x] the docs build\n")
        self.receipt(THEIRS, SENDER, state="running", finished_at=None)
        watch.seat_write(SEAT, wait={"on": THEIRS, "kind": "run", "at": NOW - 300})

    def receipt(self, name, seat, **state):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "title": f"Task {name}",
                                      "launched_session": seat, "repo": str(self.root / seat),
                                      "started_at": NOW - 600, **state})

    def ticked(self):
        """The lines one wait pass typed into the seat."""
        before = len(self.typed)
        self.tick()
        return self.typed[before:]

    def test_one_tick_types_the_line_once_and_the_wait_is_over(self):
        typed = self.ticked()
        self.assertEqual(len(typed), 1, typed)
        self.assertTrue(typed[0].endswith(OVER), typed)
        self.assertTrue(watch.seat_read(SEAT)["wait"]["over"])
        self.assertIsNone(watch.waiting_on(SEAT))
        self.assertEqual(self.ticked(), [])

    def test_a_run_of_its_own_awaiting_live_holds_the_line_until_it_is_live(self):
        merged = {"state": "pass", "verdict": "PASS", "merged": True, "finished_at": NOW - 60,
                  "health": {"command": "curl -fsS https://acme.test/ok"}}
        self.receipt(MINE, SEAT, **merged)
        self.assertEqual(self.ticked(), [])
        self.assertEqual(watch.waiting_on(SEAT)["on"], THEIRS)
        self.receipt(MINE, SEAT, **merged, live_at=NOW - 10)
        typed = self.ticked()
        self.assertEqual(len(typed), 1, typed)
        self.assertTrue(typed[0].endswith(OVER), typed)

    def test_an_open_plan_line_keeps_the_wait(self):
        config.plan_path(SEAT).write_text(
            "- [ ] the docs build · check: `false` · acme · written 2026-10-24 12:00\n")
        self.assertEqual(self.ticked(), [])
        self.assertEqual(watch.waiting_on(SEAT)["on"], THEIRS)

    def test_a_gone_seat_is_told_without_reopening_and_reads_done(self):
        self.seat["exited"] = True
        with patch.object(watch, "revive") as revive:
            self.assertEqual(self.ticked(), [])
        revive.assert_not_called()
        self.assertTrue(watch.seat_read(SEAT)["wait"]["told"])
        self.assertEqual(watch.session_state(SEAT, NOW, session=self.seat, cfg=self.cfg)["word"],
                         "done")

    def test_ak_wait_from_such_a_seat_is_refused_and_writes_no_wait(self):
        watch.seat_write(SEAT, wait=None)
        err = io.StringIO()
        with patch.dict(os.environ, {config.SESSION_ENV: SEAT}), \
                patch.object(sys, "argv", [str(REPO / "bin/ak"), "wait", THEIRS]), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(AK_MAIN(), 1)
        self.assertEqual(err.getvalue().count("\n"), 1, err.getvalue())
        self.assertIsNone(watch.seat_read(SEAT).get("wait"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
