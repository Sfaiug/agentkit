"""A seat's plan follows it through a rename: `ak plan` reads it under the new name and the old.

A seat's done and its menu bar are counted from its plan.  A renamed seat keeps its
conversation, and the orchestrator in it still carries the name it was launched with in
AGENTKIT_SESSION, so its plan must read the same under either name, or a rename would lose the
seat's work.  `ak orch rename` moves `plan-<old>.md` to `plan-<new>.md`; a plan still kept under
the old name is listed for the new one, and a check passing on main is ticked in that same
file.  Black-box: the program `AK_BIN` names, judged by what `ak plan` lists and the plan files
under HOME; this test fails against `/bin/false`.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

STATE = ".agentkit/state"


def plan(rig):
    """A plan as `ak plan` writes one, on the rig's project: a check line, an eye line from
    before every line had a check, and a review follow-up deferred to a run."""
    root = rig.git("rev-list", "--max-parents=0", "HEAD")[:12]
    project = f"~/code/{rig.name}#{root}"
    return [f"- [ ] the parser reads tabs · check: `test -f tabs.txt` · {project} · "
            f"written 2026-10-01 09:00 on {root}",
            f"- [x] the logo looks calm · your eye · {project} · written 2026-10-01 09:05",
            f"- [ ] the api retries · check: `test -f retry.txt` · {project} · deferred · "
            f"written 2026-10-01 09:10 on {root}"]


def listed(home, seat):
    """`ak plan` run in the seat by that name: its plan lines, in the order it numbered them."""
    done = home.ak("plan", env={"AGENTKIT_SESSION": seat, "COLUMNS": "250"})
    assert done.code == 0, f"ak plan in {seat}: {done.code} {done.err}"
    rows = [re.fullmatch(r" *(\d+) +(- \[.*?) *", row) for row in done.out.splitlines()]
    assert all(rows), done.out
    assert [int(row[1]) for row in rows] == list(range(1, len(rows) + 1)), done.out
    return [row[2] for row in rows]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PlanUnderTheOldName(unittest.TestCase):
    """fix-api renamed parser-fix, its plan still under fix-api, as a seat renamed writes it."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets")
        self.lines = plan(self.rig)
        self.old = self.home.write(f"{STATE}/plan-fix-api.md",
                                   "".join(f"{line}\n" for line in self.lines))
        self.home.write(f"{STATE}/session-fix-api.json", {"renamed": "parser-fix"})
        self.home.write(f"{STATE}/session-parser-fix.json",
                        {"orchestrator": "opus", "workers": ["opus"], "cwd": str(self.rig.path),
                         "repo": str(self.rig.path), "created": int(time.time()) - 600})

    def test_the_new_name_and_the_old_one_both_list_the_plan_written_under_the_old(self):
        for seat in ("parser-fix", "fix-api"):
            with self.subTest(seat=seat):
                self.assertEqual(listed(self.home, seat), self.lines)

    def test_a_check_passing_on_main_is_ticked_in_the_plan_it_was_read_from(self):
        sha = self.rig.commit({"tabs.txt": ""}, "tabs")
        shown = listed(self.home, "parser-fix")
        kept = self.old.read_text().splitlines()
        self.assertEqual(shown, kept)
        self.assertTrue(kept[0].startswith(f"- [x] {self.lines[0][6:]} · done {sha[:12]}"),
                        kept[0])
        self.assertEqual(kept[1:], self.lines[1:])
        self.assertFalse((self.home.path / STATE / "plan-parser-fix.md").exists())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PlanThroughOrchRename(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.lines = plan(Rig(cls.home, "widgets"))
        Seat(cls.home, "alpha")
        cls.home.write(f"{STATE}/plan-alpha.md", "".join(f"{line}\n" for line in cls.lines))
        cls.renamed = cls.home.ak("orch", "rename", "alpha", "beta")

    def test_ak_orch_rename_moves_the_plan_to_the_new_name(self):
        self.assertEqual(self.renamed.code, 0, self.renamed.err)
        state = self.home.path / STATE
        self.assertEqual((state / "plan-beta.md").read_text().splitlines(), self.lines)
        self.assertFalse((state / "plan-alpha.md").exists())

    def test_the_renamed_seat_lists_its_plan_under_either_name(self):
        self.assertEqual(self.renamed.code, 0, self.renamed.err)
        for seat in ("beta", "alpha"):
            with self.subTest(seat=seat):
                self.assertEqual(listed(self.home, seat), self.lines)


if __name__ == "__main__":
    unittest.main()
