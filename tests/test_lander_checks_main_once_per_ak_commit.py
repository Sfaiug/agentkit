"""After an ak update, a lander checks main once; passes from before it then still count.

Offline: local Git and real suites, with isolated state and fake wakes, as in
test_lander_red_main.  Evidence is stamped with an invented earlier ak commit.
"""

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander_red_main as red_main
from agentkit import land, record, run

SUITE = red_main.SUITE


class ChecksMainOncePerAkCommit(unittest.TestCase):
    # RedMain's fixture, not its tests
    setUp = red_main.RedMain.setUp
    commit, advance, check = red_main.RedMain.commit, red_main.RedMain.advance, red_main.RedMain.check
    wait, member, prepare = red_main.RedMain.wait, red_main.RedMain.member, red_main.RedMain.prepare

    def passed_earlier(self, *members):
        """Record each member's stack, stacked in order, as passed under another ak commit."""
        run.fetch(self.repo, "origin")
        top = tip = run.git(self.repo, "rev-parse", "origin/main")
        trees = []
        with ExitStack() as opened:
            for directory in members:
                saved = record.read_state(directory)
                scratch, text = land._stack_member(self.repo, saved, top, "origin/main", opened)
                self.assertFalse(text)
                trees.append(run.git(scratch, "rev-parse", "HEAD^{tree}"))
                land.note(self.turn, [trees[-1]], "earlier",
                          checks=land._landing_checks(directory, saved, scratch, tip))
                top = run.git(scratch, "rev-parse", "HEAD")
        path = land._trees(self.turn)[0]
        kept = json.loads(path.read_text())
        for evidence in kept["trees"].values():
            evidence["code"] = "an-earlier-ak-commit"
        path.write_text(json.dumps(kept))
        return trees

    def test_earlier_passes_land_after_one_check_of_main(self):
        first = self.member()
        later = self.member("later", joined=2, **{"later.txt": "later\n"})
        self.advance()
        trees = self.passed_earlier(first, later)
        land.check_line(self.turn)
        self.assertEqual([cmds for cmds, *_ in self.checks], [[SUITE]])
        self.assertEqual([self.wait(first)["land"], self.wait(later)["land"]], trees)
        self.assertEqual(self.prepared, [])

    def test_a_main_checked_under_this_commit_is_not_checked_again(self):
        first = self.member()
        self.advance()
        self.passed_earlier(first)
        land.note(self.turn, [run.git(self.repo, "rev-parse", "origin/main^{tree}")], "earlier",
                  checks=[SUITE])
        land.check_line(self.turn)
        self.assertEqual(self.checks, [])
        self.assertIn("land", self.wait(first))


if __name__ == "__main__":
    unittest.main()
