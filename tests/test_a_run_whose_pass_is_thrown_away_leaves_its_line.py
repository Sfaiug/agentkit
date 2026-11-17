"""A run whose saved PASS is thrown away leaves its line.

Its place there was the reviewed commit's.  Kept without the review, the run's own delivery and
the lander's check of the whole line both read a review that was gone, so nothing behind it
landed either.  Offline: one record in memory, no run started.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import land, transitions

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
    def test_the_place_goes_with_the_review(self):
        state, logs = passed(), []
        transitions.invalidate_saved_pass(state, CFG, logs.append)
        self.assertEqual((state["verdict"], logs, land.member(state)), ("PASS", [], True))
        # the reviewer's mark is no longer defined: the saved PASS cannot be judged eligible
        cfg = {**CFG, "models": {"alpha": CFG["models"]["alpha"]}}
        transitions.invalidate_saved_pass(state, cfg, logs.append)
        self.assertEqual((state["verdict"], state["review"], state["review_pending"]["round"]),
                         (None, None, 2))
        self.assertNotIn("waiting_on", state)
        self.assertFalse(land.member(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
