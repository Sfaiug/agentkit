"""`ak plan` proves its lines on origin's default branch: it ticks each open check line whose
check passes there now, naming the commit it passed on, and opens again a line ticked by hand
that nothing proved.

A seat's plan is how ak knows its work is done, with nobody declaring it, so a tick must come
from the check passing on the code that landed, never from the seat's own checkout or a hand on
the box.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py
in a seat's environment, over a project whose origin is a bare repository on disk, and this
test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

PARSER = "the parser works · check: `python3 tests/test_parser.py`"
FOLLOW_UP = "the follow-up is fixed · check: `test -f fixed.txt`"


class PlanTicks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "acme")
        cls.root = cls.rig.git("rev-list", "--max-parents=0", "HEAD")[:12]
        cls.where = f"~/code/acme#{cls.root}"
        cls.rig.commit({"fixed.txt": "fixed\n"}, "add fixed")
        cls.done = f"done {cls.rig.head()[:12]} add fixed"
        # The fix landed from elsewhere: the seat's checkout has not fetched it, and passes the
        # parser check only with a file it never committed.
        cls.rig.git("reset", "-q", "--hard", "HEAD~1")
        cls.rig.git("update-ref", "refs/remotes/origin/main", "HEAD")
        (cls.rig.path / "tests").mkdir()
        (cls.rig.path / "tests" / "test_parser.py").write_text("raise SystemExit(0)\n")
        Seat(cls.home, "fix-api", alive=False, cwd=cls.rig.path,
             record={"repo": str(cls.rig.path)})
        cls.plan = ".agentkit/state/plan-fix-api.md"

    def line(self, mark, what, tail=""):
        return f"- [{mark}] {what} · {self.where} · written 2026-10-20 09:00{tail}"

    def listed(self, *lines):
        """The plan given, listed: what `ak plan` printed and what the plan holds after."""
        self.home.write(self.plan, "".join(f"{line}\n" for line in lines))
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": "fix-api", "COLUMNS": "250"})
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines(), (self.home.path / self.plan).read_text().splitlines()

    def test_a_line_whose_check_now_passes_on_main_is_ticked_with_that_commit(self):
        parser = self.line(" ", PARSER, f" on {self.root}")
        out, stored = self.listed(parser, self.line(" ", FOLLOW_UP))
        ticked = self.line("x", FOLLOW_UP, f" · {self.done}")
        self.assertEqual(out, [f" 1  {parser}", f" 2  {ticked}"])
        self.assertEqual(stored, [parser, ticked])

    def test_a_listing_leaves_no_checkout_behind(self):
        self.listed(self.line(" ", PARSER), self.line(" ", FOLLOW_UP))
        wt = self.home.path / ".agentkit" / "wt"
        left = sorted(p.name for p in wt.iterdir()) if wt.is_dir() else []
        self.assertEqual([name for name in left if name.startswith("plan-")], [])
        self.assertEqual(self.rig.git("worktree", "list", "--porcelain").count("worktree "), 1)

    def test_a_hand_ticked_line_whose_check_fails_is_open_again(self):
        schema = "the schema loads · check: `test -f schema.json`"
        out, stored = self.listed(self.line("x", PARSER, f" on {self.root}"),
                                  self.line("x", schema, " · done by hand"))
        opened = [self.line(" ", PARSER, f" on {self.root}"), self.line(" ", schema)]
        self.assertEqual(out, [f" 1  {opened[0]}", f" 2  {opened[1]}"])
        self.assertEqual(stored, opened)

    def test_a_hand_ticked_line_whose_check_passes_gains_the_commit_it_passed_on(self):
        out, stored = self.listed(self.line("x", FOLLOW_UP))
        ticked = self.line("x", FOLLOW_UP, f" · {self.done}")
        self.assertEqual(out, [f" 1  {ticked}"])
        self.assertEqual(stored, [ticked])

    def test_a_line_proven_done_is_not_checked_again(self):
        # once its check passed on a commit, the line stays done whatever main does since
        proven = self.line("x", "the cache is gone · check: `test -f cache.db`",
                           f" · done {self.root} init")
        out, stored = self.listed(proven)
        self.assertEqual(out, [f" 1  {proven}"])
        self.assertEqual(stored, [proven])


if __name__ == "__main__":
    unittest.main()
