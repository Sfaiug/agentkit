"""A run whose saved PASS is thrown away leaves its line.

Its place there was the reviewed commit's.  Kept without the review, the run's own delivery and
the lander's check of the whole line both read a review that was gone, so nothing behind it
landed either: the place goes first, and only then the review.  Offline: records in memory, no
run started.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import land, roundloop, transitions

MODEL = {"harness": "test", "model": "m", "effort": "high"}
CFG = {"providers": {"a": {}, "b": {}},
       "models": {"alpha": {**MODEL, "provider": "a"}, "beta": {**MODEL, "provider": "b"}}}


def passed():
    return {"state": "waiting", "verdict": "PASS", "repo": "widget", "rounds": 3,
            "executor": "alpha", "reviewer": "beta",
            "round_summaries": [{"round": 1, "verdict": "PASS", "summary": "built"}],
            "review": {"verdict": "PASS", "returncode": 0, "done_when": True,
                       "executor": "alpha", "reviewer": "beta", "executor_provider": "a",
                       "reviewer_provider": "b", "head_sha": "head", "tree_sha": "tree"},
            "waiting_on": {"line": ".merge-acme.lock", "joined": 1.0, "land": "tree"}}


class ThrownAwayPass(unittest.TestCase):
    def test_the_place_goes_before_the_review(self):
        state, logs = passed(), []
        self.assertFalse(transitions.leaves_line(state, CFG))
        self.assertTrue(land.member(state))
        # the reviewer's mark is no longer defined: the saved PASS cannot be judged eligible
        cfg = {**CFG, "models": {"alpha": CFG["models"]["alpha"]}}
        transitions.invalidate_saved_pass(state, cfg, logs.append)
        self.assertEqual((state["verdict"], logs, land.member(state)), ("PASS", [], True))
        self.assertTrue(transitions.leaves_line(state, cfg))
        self.assertNotIn("waiting_on", state)
        self.assertFalse(land.member(state))
        transitions.invalidate_saved_pass(state, cfg, logs.append)
        self.assertEqual((state["verdict"], state["review"], state["review_pending"]["round"]),
                         (None, None, 2))

    def test_a_green_place_kept_without_its_review_goes(self):
        # an older ak erased a line member's PASS and kept its place (before 18 Nov 2026)
        state = {**passed(), "verdict": None, "review": None,
                 "review_pending": {"round": 2, "summary": "built"}}
        lp = SimpleNamespace(state=state, cfg=CFG, log=print, save=lambda: None, rnd=1)
        with patch.object(roundloop, "resume_review", return_value="PASS") as resumed:
            roundloop.rounds(lp)
        self.assertTrue(resumed.called)
        self.assertNotIn("waiting_on", state)
        # a member under a landing fix waits without its PASS, and keeps its place
        fixing = {**passed(), "verdict": None, "review": None}
        fixing["waiting_on"]["fix"] = {"line": "red", "log": "red.log"}
        self.assertFalse(transitions.leaves_line(fixing, CFG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
