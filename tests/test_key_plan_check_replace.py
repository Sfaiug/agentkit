"""`ak plan check N 'COMMAND'` puts another check on plan line N, proven on the commit it names.

A seat swaps a review's probe for its own test this way, often after the work has landed: the
new check must fail on the commit the line's check was proven failing on, never on the default
branch as it is now, or a check that passes everywhere would close the line unearned.  The line
comes back open and the seat's own, its outcome, project, stamp and commit kept; a line from
before lines named a commit takes the check unproven; anything else is refused with exit 2 and
the plan left as it was.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py on a project tests/fixtures/gitrig.py keeps, and this test fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

USAGE = ("usage: ak plan | ak plan add \"OUTCOME\" --check 'COMMAND' | "
         "ak plan check N 'COMMAND'")
PLAN = ".agentkit/state/plan-fix-api.md"


class PlanCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "acme")
        cls.root = rig.head()[:12]
        # the code before the work: notes.txt is there, the parser is not
        cls.base = rig.commit({"notes.txt": "draft\n"}, "add notes")[:12]
        rig.git("rm", "-q", "notes.txt")
        cls.land = rig.commit({"parser.txt": "", "parser_ok.txt": ""}, "land the parser")[:12]
        cls.project = f"~/code/acme#{cls.root}"
        cls.gone = f"~/code/gone#{cls.root}"
        Seat(cls.home, "fix-api", cwd=rig.path, record={"repo": str(rig.path)}, alive=False)

    def plan(self, *lines):
        return self.home.write(PLAN, "".join(f"{line}\n" for line in lines)).read_text()

    def stored(self):
        return (self.home.path / PLAN).read_text()

    def ak(self, *args):
        return self.home.ak("plan", *args, env={"AGENTKIT_SESSION": "fix-api"})

    def taken(self, args, line):
        done = self.ak(*args)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out, f"{line}\n")
        return done

    def refused(self, args, error, before):
        with self.subTest(args=args):
            done = self.ak(*args)
            self.assertEqual(done.code, 2, done.out)
            self.assertEqual(done.err, f"ak plan: {error}\n")
            self.assertEqual(done.out, "")
            self.assertEqual(self.stored(), before)

    def test_a_check_failing_on_the_lines_commit_takes_its_place_and_reopens_it(self):
        self.plan("# fix-api", "",
                  "- [ ] tidy the docs",
                  f"- [x] the parser works · check: `test -f parser.txt` · {self.project} · "
                  f"written 2026-10-02 12:40 on {self.base} · done {self.land} land the parser",
                  "- [ ] write the changelog")
        # parser_ok.txt is on the default branch already: only the line's commit judges it
        line = (f"- [ ] the parser works · check: `test -f parser_ok.txt` · {self.project} · "
                f"written 2026-10-02 12:40 on {self.base}")
        self.taken(("check", "2", "test -f parser_ok.txt"), line)
        self.assertEqual(self.stored(), "".join(f"{each}\n" for each in (
            "# fix-api", "", "- [ ] tidy the docs", line, "- [ ] write the changelog")))

    def test_a_deferred_line_becomes_the_seats_own_and_keeps_its_commit(self):
        self.plan(f"- [ ] the api answers · check: `test -f api_probe.txt` · {self.project} · "
                  f"deferred · written 2026-10-02 12:41 on {self.base}")
        line = (f"- [ ] the api answers · check: `test -f api_ok.txt` · {self.project} · "
                f"written 2026-10-02 12:41 on {self.base}")
        self.taken(("check", "1", "test -f api_ok.txt"), line)
        self.assertEqual(self.stored(), f"{line}\n")

    def test_a_check_passing_on_the_lines_commit_is_refused(self):
        before = self.plan(
            f"- [ ] the parser works · check: `test -f parser.txt` · {self.project} · "
            f"written 2026-10-02 12:40 on {self.base}")
        error = (f"this check already passes on {self.base}, the commit line 1 names, so it "
                 "proves nothing; write one that fails until the work is done")
        # notes.txt is gone from the default branch, but the line's commit holds it
        for check in ("test -f notes.txt", "true"):
            self.refused(("check", "1", check), error, before)

    def test_a_line_naming_no_commit_takes_its_new_check_unproven(self):
        self.plan(f"- [ ] the follow-up is fixed · check: `test -f fixed.txt` · {self.project}"
                  " · deferred · written 2026-10-02 12:42",
                  f"- [x] the old line · check: `test -f old.txt` · {self.gone} · "
                  "written 2026-10-02 12:43 · done 0123456789ab tidy")
        # .keep is in every commit, and `true` passes anywhere: neither check ran
        first = (f"- [ ] the follow-up is fixed · check: `test -f .keep` · {self.project} · "
                 "written 2026-10-02 12:42")
        self.taken(("check", "1", "test -f .keep"), first)
        second = f"- [ ] the old line · check: `true` · {self.gone} · written 2026-10-02 12:43"
        self.taken(("check", "2", "true"), second)
        self.assertEqual(self.stored(), f"{first}\n{second}\n")

    def test_a_line_that_is_missing_or_no_check_line_is_refused(self):
        before = self.plan(
            "- [ ] tidy the docs",
            f"- [x] the look is right · your eye · {self.project} · written 2026-10-02 12:45",
            f"- [ ] the gone line · check: `test -f gone.txt` · {self.gone} · "
            f"written 2026-10-02 12:44 on {self.base}")
        for number in ("4", "0"):
            self.refused(("check", number, "false"),
                         f"no plan line {number}; `ak plan` lists them", before)
        for number in ("1", "2"):
            self.refused(("check", number, "false"), "only a check line takes another check",
                         before)
        self.refused(("check", "3", "false"), f"this host has no checkout of {self.gone}",
                     before)

    def test_a_check_not_one_command_or_naming_the_checkout_is_refused(self):
        before = self.plan(
            f"- [ ] the parser works · check: `test -f parser.txt` · {self.project} · "
            f"written 2026-10-02 12:40 on {self.base}")
        for check in ("test -f `pwd`/x", "test -f a\ntest -f b"):
            self.refused(("check", "1", check),
                         "a check is one shell command without backticks or line breaks", before)
        self.refused(("check", "1", "test -f ~/code/acme/parser_ok.txt"),
                     "this check holds ~/code/acme, the path of the project's checkout, but a "
                     "check runs in a clean checkout of its default branch: name paths relative "
                     "to the repository, as in `python3 tests/test_x.py`", before)

    def test_arguments_of_any_other_shape_print_the_usage(self):
        before = self.plan(
            f"- [ ] the parser works · check: `test -f parser.txt` · {self.project} · "
            f"written 2026-10-02 12:40 on {self.base}")
        for args in (("bogus",), ("check", "one", "false"), ("check", "-1", "false"),
                     ("check", "1"), ("check", "1", "false", "true"), ("check",)):
            self.refused(args, USAGE, before)


if __name__ == "__main__":
    unittest.main()
