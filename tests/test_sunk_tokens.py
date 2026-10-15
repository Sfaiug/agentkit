"""The scoreboard shows the share of each week's tokens that bought no merge: every token an
ended run spent, executor's and reviewer's, where the run delivered nothing, against the week's
recorded tokens.  The cost the medians per merged run leave out.

Offline: a sandbox HOME with its own history database, git answering nothing.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, scoreboard, terminal

NOW = 1_800_000_000
WEEK = 7 * 86400


class Sunk(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-sunk-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, value in (("HOME", root / ".agentkit"), ("RUNS", root / ".agentkit" / "runs"),
                            ("REPO", root / "toolkit")):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"HOME": str(root), "NO_COLOR": "1"})
        env.start()
        self.addCleanup(env.stop)
        for target, name, value in ((scoreboard, "_git", lambda *args, **kw: None),
                                    (scoreboard.time, "time", lambda: NOW),
                                    (terminal, "content_width", lambda: 400)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ended(self, name, *, ago=1, state="pass", merged=True, tokens=(80, 20), repo="acme"):
        finish = NOW - ago
        history.start_run(name, repo=repo, started_at=finish - 3600, change=name)
        history.finish_run(name, final_state=state, verdict=state.upper(), finished_at=finish,
                           rounds_used=1, changed_lines=0 if merged else None)
        history.update_run(name, executor_tokens=tokens[0], reviewer_tokens=tokens[1])

    def test_the_tokens_of_runs_that_delivered_nothing_are_the_week_s_sunk_share(self):
        self.ended("merged", tokens=(300, 100))
        self.ended("own", repo="toolkit", tokens=(200, 100))        # ak's own count the same
        self.ended("failed", state="fail", merged=False, tokens=(150, 50))
        self.ended("blocked", state="blocked", merged=False, tokens=(100, 0))
        self.ended("scratch", merged=False, tokens=(50, 50))        # passed, delivered nothing
        self.ended("not-needed", state="not_needed", merged=False, tokens=(900, 0))   # no work
        self.ended("old", ago=WEEK + 1, state="fail", merged=False, tokens=(10, 10))
        board = scoreboard.compute(NOW)
        # 400 of the week's 1,100 recorded tokens (the not-needed run's never count as work)
        self.assertEqual(board["sunk"], [{"share": 4 / 11, "tokens": 400}, {"share": 1.0, "tokens": 20}])
        row = [line for line in scoreboard.render() if line.startswith("sunk")][0]
        self.assertIn("36% of the week's tokens, 400, went to runs that never merged", row)
        self.assertIn("100% of the week's tokens, 20, went to runs that never merged", row)

    def test_a_week_without_recorded_tokens_shows_none(self):
        self.ended("silent", tokens=(None, None))
        board = scoreboard.compute(NOW)
        self.assertEqual(board["sunk"], [None, None])
        self.assertIn("sunk      no tokens recorded", "\n".join(scoreboard.render()))


if __name__ == "__main__":
    unittest.main()
