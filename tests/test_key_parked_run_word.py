"""A seat at its prompt whose own run is parked reads `needs you`, naming the run.

A stalled run, a run left undecided once the seat's plan is done, and a merge wait older than
the tick's day: nothing but the owner moves any of them, so the seat that launched it says so,
and for a stalled run it says the one command that moves it, whole however long the run's id.
A turn in flight still reads `working`, a merge wait under a day is still the tick's, and
another seat's parked run is not this seat's word.  The runs are records under
~/.agentkit/runs as a run leaves them.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

DAY = 86400
WAIT = "origin/main is red; retried after the next merge to origin/main"
# a long id, and a long step in its recorded error: the error may be cut, the command never is
STALLED = "20261001-0100-fix-api-a-long-integration-command-in-the"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ParkedRunWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def run_of(self, seat, run_id, **state):
        """A run that seat launched two days ago, as its record stands now."""
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": f"Task {run_id}", "launched_session": seat,
            "started_at": time.time() - 2 * DAY, **state})

    def stalled(self, seat, run_id):
        step = "done-when " + "x" * 240
        self.run_of(seat, run_id, state="stalled", stalls=[{"step": step}], finished_at=None,
                    stalled_notified=False,
                    error=f"stalled three times at {step}; parked: ak run resume {run_id}")

    def merge_wait(self, seat, run_id, ended_ago):
        self.run_of(seat, run_id, state="waiting", verdict="PASS", error=WAIT, merge_note=WAIT,
                    waiting_on={"ref": "origin/main"}, finished_at=time.time() - ended_ago)

    def why(self, name):
        """`ak orch why`'s first line and its reason."""
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        reason = next(line for line in lines if line.startswith("  reason:"))
        return lines[0], reason.split(":", 1)[1].strip()

    def test_a_stalled_run_needs_you_and_says_how_to_resume_it(self):
        Seat(self.home, "acme")
        Seat(self.home, "beta")
        self.stalled("acme", STALLED)
        self.assertEqual(self.why("acme"), (
            "acme  needs you", f"run {STALLED} stalled: resume it with `ak run resume {STALLED}`"))
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        row = next(line for line in done.out.splitlines() if line.startswith("acme "))
        self.assertIn("! needs you", row)
        self.assertEqual(self.why("beta"), ("beta  idle", "-"))    # not its run

    def test_a_turn_in_flight_reads_working_over_its_stalled_run(self):
        Seat(self.home, "delta", screen="claude-working-pane.txt")
        self.stalled("delta", "20261001-0200-fix-docs")
        self.assertEqual(self.why("delta")[0], "delta  working")

    def test_a_run_left_undecided_once_the_plan_is_done_needs_you(self):
        Seat(self.home, "gamma")
        now = time.time()
        self.run_of("gamma", "20261001-0300-fix-cli", state="interrupted", recovery_pending=True,
                    interrupted_at=now - 3600, handed_back=now - 3500,
                    interruption_reason="the loop died mid-review")
        self.home.write(".agentkit/state/plan-gamma.md", "- [x] Shipped it\n")
        self.assertEqual(self.why("gamma"), (
            "gamma  needs you", "run 20261001-0300-fix-cli parked: the loop died mid-review"))

    def test_a_merge_wait_past_the_ticks_day_needs_you(self):
        Seat(self.home, "kappa")
        Seat(self.home, "omega")
        self.merge_wait("kappa", "20261001-0400-fix-ui", DAY + 60)
        self.merge_wait("omega", "20261001-0500-fix-db", 3600)
        self.assertEqual(self.why("kappa"), (
            "kappa  needs you", f"run 20261001-0400-fix-ui waits to merge: {WAIT}"))
        self.assertEqual(self.why("omega")[0], "omega  working")    # the tick's, for a day


if __name__ == "__main__":
    unittest.main()
