"""`ak plan` lists every box line of the plan numbered, wrapped to the terminal, and leaves an
eye line as written while a deferred line ticks, its mark kept, once its check passes.

The listing is how a seat and the owner read what is left, and line numbers are what
`ak plan check <n>` takes, so the numbering and the wrapping must hold at any width.  An eye
line is the owner's to judge live, never the seat's to prove, and a deferred line is a run's
until it ticks.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py in a seat's environment, over a project whose origin is a bare
repository on disk, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

PLAN = ".agentkit/state/plan-fix-api.md"


class PlanListing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "acme")
        cls.root = cls.rig.git("rev-list", "--max-parents=0", "HEAD")[:12]
        cls.where = f"~/code/acme#{cls.root}"
        cls.head = cls.rig.commit({"fixed.txt": "fixed\n"}, "add fixed")[:12]
        Seat(cls.home, "fix-api", alive=False, cwd=cls.rig.path,
             record={"repo": str(cls.rig.path)})

    def listed(self, lines, columns):
        """The plan given, listed at that width: what `ak plan` printed and what the plan holds
        after."""
        self.home.write(PLAN, "".join(f"{line}\n" for line in lines))
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": "fix-api", "COLUMNS": str(columns)})
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines(), (self.home.path / PLAN).read_text().splitlines()

    def test_box_lines_are_numbered_and_wrapped_under_their_text(self):
        plan = [f"- [ ] the parser works · check: `python3 tests/test_parser.py` · {self.where}"
                f" · written 2026-10-20 09:00 on {self.root}",
                "- [x] shipped the parser", "# notes"]
        out, stored = self.listed(plan, 60)
        self.assertEqual(out, [" 1  - [ ] the parser works · check: `python3",
                               f"    tests/test_parser.py` · {self.where} ·",
                               f"    written 2026-10-20 09:00 on {self.root}",
                               " 2  - [x] shipped the parser"])
        self.assertLessEqual(max(len(line) for line in out), 60)
        self.assertEqual(stored, plan)    # what the listing leaves out is still the plan's

    def test_the_number_column_is_two_wide_until_it_needs_three(self):
        steps = [f"- [x] step {n}" for n in range(1, 11)]
        out, _ = self.listed(steps, 60)
        self.assertEqual(out[0], " 1  - [x] step 1")
        self.assertEqual(out[-1], "10  - [x] step 10")
        long = "- [x] the old importer is gone and every caller reads the new one instead"
        out, _ = self.listed([long, *(f"- [x] step {n}" for n in range(2, 101))], 60)
        self.assertEqual(out[:3], ["  1  - [x] the old importer is gone and every caller reads",
                                   "     the new one instead", "  2  - [x] step 2"])
        self.assertEqual(out[-2:], [" 99  - [x] step 99", "100  - [x] step 100"])

    def test_an_eye_line_is_listed_and_kept_as_written(self):
        eye = f"- [ ] the menu looks right · your eye · {self.where} · written 2026-10-20 09:00"
        # a check line beside it, so the plan is written back after its check ran
        check = (f"- [ ] the parser works · check: `python3 tests/test_parser.py` · {self.where}"
                 " · written 2026-10-20 09:00")
        out, stored = self.listed([eye, check], 250)
        self.assertEqual(out, [f" 1  {eye}", f" 2  {check}"])
        self.assertEqual(stored, [eye, check])

    def test_a_deferred_line_ticks_once_its_check_passes_and_stays_deferred(self):
        fixed, later = ("the follow-up is fixed · check: `test -f fixed.txt`",
                        "the importer is gone · check: `test -f gone.txt`")
        mark = f"· {self.where} · deferred · written 2026-10-20 09:00"
        out, stored = self.listed([f"- [ ] {fixed} {mark}", f"- [ ] {later} {mark}"], 250)
        ticked = f"- [x] {fixed} {mark} · done {self.head} add fixed"
        self.assertEqual(out, [f" 1  {ticked}", f" 2  - [ ] {later} {mark}"])
        self.assertEqual(stored, [ticked, f"- [ ] {later} {mark}"])


if __name__ == "__main__":
    unittest.main()
