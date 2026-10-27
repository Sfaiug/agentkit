"""A landing fixer that commits nothing leaves the reviewed head re-reviewed, and the PR lands.

The PR passed review at its head, landing rebased the checkout onto a moved target and the suite
went red on a flake that was not the PR's.  The fixer starts from the reviewed head, commits
nothing, and the round after it judges the commit the checkout holds.  Offline: the own-PR
line fixture with the real `run.fix_own_pr`, its model faked as the landing fixer tests fake it.
"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_own_pr_line as line
from agentkit import gate, hand_in, land, run, turns


class LandingFixerCommitsNothing(line.OwnPrLineFixture, unittest.TestCase):
    def test_a_fixer_that_commits_nothing_gets_its_head_re_reviewed_and_merged(self):
        directory, url = self.own_pr("second", 1)
        reviewed = self.prs[url]["head"]
        self.advance()      # the target moves: the check before the line rebases the reviewed head
        flakes = [True]

        def flaky(cmds, cwd, log_path, *args, **kw):
            if flakes and cmds:
                flakes.pop()
                cmds = ["echo the clock slipped; exit 1"]
            return self.check(cmds, cwd, log_path, *args, **kw)

        starts = []

        def execute(lp, role, _text, name):
            starts.append(run.git(lp.wt, "rev-parse", "HEAD"))
            out = turns.free_dir(lp, name)
            out.mkdir(parents=True)
            rows = [{"kind": "turn", "workspace": str(lp.wt), "role": role, "findings": []}, {"kind": "done"}]
            (out / hand_in.FILE).write_text("".join(json.dumps(row) + "\n" for row in rows))
            (out / "final.md").write_text("## Summary\nThe red was a flake; nothing to fix.")
            return "## Summary\nThe red was a flake; nothing to fix."

        with patch.object(gate, "run_done_when", side_effect=flaky), \
                patch.object(run, "execute", side_effect=execute):
            state = self.review(directory, url)
        self.assertEqual(flakes, [], "the suite never went red")
        self.assertEqual(starts, [reviewed], "the fixer did not start from the reviewed head")
        self.assertEqual(state["state"], "waiting", state.get("error"))
        self.assertEqual(self.prs[url]["head"], reviewed, "the rebase was pushed to the PR")
        self.assertIn("Re-review after the landing fix", self.reviews[-1])
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"], state.get("error"))
        self.assertEqual(len(self.reviews), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
