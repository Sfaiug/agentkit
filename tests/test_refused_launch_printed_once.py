"""A launch refused by the `ak run` a seat typed is told there, once.

That command prints the refusal and exits 2 where the seat reads it; typed back into the seat
as an ending as well, it opened a turn for news the seat had read (19 Oct 2026: 22 launches
refused in 14 days, every one typed back, 7 then stopped by hand).  A launch ak starts for the
seat, as the tick restarts one, prints to no seat, so its refusal is still handed back.
Offline, on the `fixtures.own_pr` stage.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import OwnPr, URL
from agentkit import config, handback, record, run, transitions


class RefusedLaunchPrintedOnce(OwnPr):
    def setUp(self):
        super().setUp()
        # a seat's own PR stacked on an unmerged branch: refused before anything runs
        self.git("push", "-q", "origin", "main:refs/heads/earlier")
        self.pr.update(baseRefName="earlier")
        self.stack.enter_context(patch.object(run, "spawn_bg", return_value=0))

    def test_the_seat_s_own_refused_launch_is_never_typed_back(self):
        before = set(config.RUNS.iterdir())
        with self.assertRaises(config.Error):
            run.review_pr_main(self.cfg, {"--review-pr": URL, "--review": None},
                               {"--bg": True}, ["--review-pr", URL, "--bg"], None)
        state = record.read_state((set(config.RUNS.iterdir()) - before).pop())
        self.assertEqual(state["state"], "error")
        self.assertEqual(self.notices, [])
        self.assertFalse(handback.owes_ending(state))     # nor does the tick offer it later
        self.assertTrue(transitions.settled(state))

    def test_a_launch_ak_starts_for_the_seat_is_still_handed_back(self):
        directory = config.RUNS / "started-again"
        directory.mkdir()
        (directory / "log.txt").touch()
        with self.assertRaises(config.Error):
            run.launch_for_seat(directory, {"launched_session": "fix-api"},
                                {"restarted": {"run": "own-pr-rounds", "why": "fixture"}},
                                self.cfg, {"--review-pr": URL})
        state = record.read_state(directory)
        self.assertEqual(state["state"], "error")
        self.assertTrue(self.notices or handback.owes_ending(state))


if __name__ == "__main__":
    unittest.main()
