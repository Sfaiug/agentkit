"""A seat at its prompt reads `working` while something of its own moves without the owner.

AGENTS.md's `working` covers a turn, its runs, a wait and a retry: a run waiting for its
provider's window to refill, an error the tick retries on its stamp, a run in line to land
however long the line takes, and the seat's own `ak wait`.  Each moves on by itself, so paging
the owner for it would be noise.  The seat's own subscription spent reads a word of its own, `out
of usage`, with when it comes back.  The same facts with nothing to move them, an exhausted run
nobody resumes, an error the tick may no longer retry, a move to another account that failed,
are the owner's: `needs you`.  Runs and the seat's live state are records under ~/.agentkit
as ak leaves them.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

DAY = 86400
PR = "https://github.com/acme/widgets/pull/7"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MovingWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def run_of(self, run_id, ended_ago, **state):
        """A seat at its prompt and one run it launched, ended `ended_ago` seconds back."""
        seat = run_id.split("-", 2)[2]
        Seat(self.home, seat)
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": f"Task {seat}", "launched_session": seat,
            "started_at": time.time() - ended_ago - 3600,
            "finished_at": time.time() - ended_ago, **state})
        return seat

    def live(self, seat, **state):
        """A seat at its prompt and its live state as the tick left it."""
        Seat(self.home, seat)
        self.home.write(f".agentkit/state/seat-{seat}.json", state)

    def why(self, seat):
        """`ak orch why`'s word and its reason."""
        done = self.home.ak("orch", "why", seat)
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        reason = next(line for line in lines if line.startswith("  reason:"))
        return lines[0].split(None, 1)[1], reason.split(":", 1)[1].strip()

    def test_a_run_waiting_for_its_window_to_refill_reads_working_however_old(self):
        for run_id, ago in (("20261001-0100-fix-api", 600), ("20261001-0200-fix-db", 2 * DAY)):
            with self.subTest(run_id):
                seat = self.run_of(run_id, ago, state="exhausted", quota_dry=True,
                                   error="anthropic usage exhausted")
                word, reason = self.why(seat)
                self.assertEqual(word, "working")
                self.assertIn(f"Task {seat}", reason)

    def test_an_exhausted_run_nothing_will_resume_needs_you(self):
        seat = self.run_of("20261001-0300-fix-ui", 600, state="exhausted", error="rounds spent")
        word, reason = self.why(seat)
        self.assertEqual(word, "needs you")
        self.assertIn("20261001-0300-fix-ui", reason)
        self.assertIn("rounds spent", reason)

    def test_an_error_the_tick_retries_on_its_stamp_reads_working(self):
        seat = self.run_of("20261001-0400-fix-cli", 120, state="error", error="git fetch failed",
                           error_retry_at=time.time() + 60, error_retries=1)
        word, reason = self.why(seat)
        self.assertEqual(word, "working")
        self.assertIn(f"Task {seat}", reason)

    def test_an_error_the_tick_may_no_longer_retry_needs_you(self):
        for run_id, ago in (("20261001-0500-fix-docs", 120), ("20261001-0600-fix-io", 2 * DAY)):
            with self.subTest(run_id):
                retry = {} if ago < DAY else {"error_retry_at": time.time() + 60}
                seat = self.run_of(run_id, ago, state="error", error="git fetch failed", **retry)
                word, reason = self.why(seat)
                self.assertEqual(word, "needs you")
                self.assertIn(run_id, reason)

    def test_a_run_in_line_to_land_reads_working_however_long_the_line_takes(self):
        seat = self.run_of("20261001-0700-fix-net", 2 * DAY, state="waiting", verdict="PASS",
                           waiting_on={"line": "acme/widgets"})
        word, reason = self.why(seat)
        self.assertEqual(word, "working")
        self.assertIn("line to land", reason)

    def test_a_turn_ended_on_ak_wait_reads_working_on_what_it_waits_for(self):
        self.live("kappa", wait={"kind": "pr", "on": PR, "at": time.time() - 60})
        self.assertEqual(self.why("kappa"), ("working", f"waiting on {PR}"))

    def test_a_spent_window_ak_resumes_reads_out_of_usage_and_says_until_when(self):
        until = "anthropic out of usage until 2026-10-21 09:00"
        self.live("omega", usage_wait={"reason": until, "until": time.time() + 3600,
                                       "since": time.time() - 60, "continue": True})
        self.assertEqual(self.why("omega"), ("out of usage", until))

    def test_a_move_to_another_account_that_failed_needs_you(self):
        failed = "anthropic account reopen failed: no login for beta"
        self.live("sigma", usage_wait={"reason": failed, "since": time.time() - 60,
                                       "continue": True})
        self.assertEqual(self.why("sigma"), ("needs you", failed))


if __name__ == "__main__":
    unittest.main()
