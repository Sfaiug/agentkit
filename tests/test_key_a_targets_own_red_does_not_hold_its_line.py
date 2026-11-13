"""A target's own red does not hold its line while its repair is under way.

The tip fails tests/test_widget.py alone, by name: stacks red in nothing else land over it, on
helper pieces too, unproven and with no trailer; one red in another test gets a fix naming that
alone, its fixer told of the target's, and one naming none is the member's where the tip fails
nothing else.  The repair lands once its stack passes the test, or is the culprit, a stack of
one tree with it answered apart.  A target red naming no test holds the line.  Offline: the
lander fixture, a shell suite, fake launches, wakes and helper, merges by a push.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander as fixture
import test_lander_red_main as red_main
from agentkit import deliver, gate, helper, land, record, roundloop, run

WIDGET, ACME = "tests/test_widget.py", "tests/test_acme.py"
# The suite fails naming nothing where crash.txt is; otherwise piece k/n runs every nth test from
# the kth, test_acme.py in 1/2 and test_widget.py in 2/2, or those AK_ONLY lists, naming each.
SUITE = ('test ! -f crash.txt || exit 1; code=0; for t in $(cat "$AK_ONLY" 2>/dev/null || ls '
         'tests/test_*.py | sed -n "${AK_SHARD%/*}~${AK_SHARD#*/}p"); do [ -f "$t" ] || continue; '
         'echo "$t" >>"${AK_RAN:-/dev/null}"; python3 "$t" || { code=1; '
         'echo "$t" >>"${AK_FAILED:-/dev/null}"; }; done; exit $code')


class ATargetsOwnRedDoesNotHoldItsLine(unittest.TestCase):
    setUp = red_main.RedMain.setUp
    prepare = red_main.RedMain.prepare
    member = red_main.RedMain.member
    assert_parked = red_main.RedMain.assert_parked
    ready_repair = red_main.RedMain.ready_repair
    commit = fixture.Lander.commit
    advance = fixture.Lander.advance
    check = fixture.Lander.check
    wait = fixture.Lander.wait

    def line(self, **broken):
        """Three members, the third failing test_acme.py, then the target `broken`: test_widget.py
        fails where broken.txt or worse.txt is, test_acme.py where acme.txt is."""
        (self.repo / "tests").mkdir()
        for test, marks in ((WIDGET, ("broken.txt", "worse.txt")), (ACME, ("acme.txt",))):
            (self.repo / test).write_text(
                f"import os\nraise SystemExit(any(map(os.path.exists, {marks})))\n")
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {SUITE}\n---\n")
        self.commit("declare the suite")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        members = (self.member("first", 1, **{"first.txt": "first\n"}),
                   self.member("second", 2, **{"second.txt": "second\n"}),
                   self.member("third", 3, **{ACME: "raise SystemExit(1)\n"}))
        self.advance(**broken)
        self.stack.enter_context(patch.object(gate, "derived_heavy_limit", return_value=2))
        return members

    def red(self, tree=None):
        """The target's red entry for `tree`, its tip's by default (`land._red`)."""
        tip = run.git(self.repo, "rev-parse", "origin/main^{tree}")
        return land._red(self.turn, tree or tip)[1]

    def deliver(self, directory):
        """Deliver `directory`'s verdict as its run does, merged by a push: its merge's body."""
        state = record.read_state(directory)
        run.git(self.repo, "checkout", state["branch"])
        lp = SimpleNamespace(state=state, wt=self.repo, run_dir=directory, target="main",
                             base_sha=state["base_sha"], log=lambda _: None,
                             write=lambda: record.save_state(directory, lp.state))

        def merged():
            lp.body = deliver.merge_body(lp, run.git(self.repo, "rev-parse", "HEAD"))
            run.git(self.repo, "push", "origin", "HEAD:main")
            return True

        self.assertTrue(deliver.land_from_line(lp, "origin/main", merged))
        return lp.body

    def test_a_stack_red_only_in_the_targets_named_red_lands_over_it_unproven(self):
        first, second, third = self.line(**{"broken.txt": "target breakage\n"})
        land.check_line(self.turn)
        # the first stack's red repeats on the tip alone, by name: the target's, repaired at once
        repair = self.prepared[0][0]
        self.assertEqual((self.red()["tests"], self.red()["run"]), ([WIDGET], repair.name))
        with record.record(third) as state:     # its fix came before the red was known
            del state["waiting_on"]["fix"]
        said = []
        land.check_line(self.turn, said.append)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(sum(WIDGET in line and repair.name in line for line in said), 1, said)
        for directory in (first, second):
            wait = self.wait(directory)
            self.assertEqual(wait["over"], [WIDGET])
            # no proof of green: no evidence, and the tree holds the target's red should it land
            self.assertIsNone(land.passed(self.turn, wait["land"]))
            self.assertEqual(self.red(wait["land"])["run"], repair.name)
        fix = self.wait(third)["fix"]
        self.assertEqual((fix["tests"], fix["excused"]), ([ACME], [WIDGET]))
        lp = SimpleNamespace(state=record.read_state(third), run_dir=third)
        with patch.object(roundloop, "execute", side_effect=StopIteration) as fixer, \
                self.assertRaises(StopIteration):
            roundloop.landing_fixer(lp, "", "final-fixer")
        self.assertIn(f"The target itself fails {WIDGET}: not this run's to mend.",
                      fixer.call_args.args[2])
        # merged without the trailer, the line still over the red on each tree it lands
        for directory in (first, second):
            self.assertNotIn("Suite-Passed-Tree", self.deliver(directory))
        self.assertEqual(self.red()["run"], repair.name)
        # the repair is a member like any other: its stack passes test_widget.py and lands
        self.ready_repair(repair)
        land.check_line(self.turn)
        wait = self.wait(repair)
        self.assertNotIn("over", wait)
        self.assertEqual(land.passed(self.turn, wait["land"])["tested"], wait["land"])
        self.assertIn(f"Suite-Passed-Tree: {wait['land']}", self.deliver(repair))
        self.assertIsNone(self.red())

    def test_a_repair_whose_stack_still_fails_the_targets_red_is_its_culprit(self):
        first, second, _ = self.line(**{"broken.txt": "target breakage\n"})
        for task in (first / "task.md", second / "task.md"):    # their checks the repair's
            task.write_text(task.read_text().replace("true  # once\n", ""))
        land.check_line(self.turn)
        repair = self.prepared[0][0]
        run.git(self.repo, "checkout", self.ready_repair(repair))
        run.git(self.repo, "checkout", "origin/main", "--", "broken.txt")
        self.commit("mend nothing")     # its stack's tree second's, as its checks are
        with record.record(repair) as state:
            state["review"].update(run.commit_identity(self.repo))
            state["waiting_on"]["joined"] = 2.5     # between second and third
        run.git(self.repo, "checkout", "main")
        land.check_line(self.turn)
        self.assertEqual([self.wait(directory)["over"] for directory in (first, second)],
                         [[WIDGET]] * 2)
        self.assertEqual(self.wait(repair)["fix"]["tests"], [WIDGET])
        self.assertNotIn("excused", self.wait(repair)["fix"])

    def test_a_member_red_naming_nothing_beside_the_targets_named_red_is_its_own(self):
        first, second, _ = self.line(**{"broken.txt": "target breakage\n"})
        land.check_line(self.turn)
        crashing = self.member("crashing", 0.5, **{"crash.txt": "crash\n"})    # first in line
        land.check_line(self.turn)
        self.assertEqual(self.red()["tests"], [WIDGET])
        self.assertEqual(self.wait(crashing)["fix"]["excused"], [WIDGET])
        self.assertEqual([self.wait(member)["over"] for member in (first, second)],
                         [[WIDGET]] * 2)

    def test_each_helper_piece_red_in_the_targets_red_alone_is_confirmed(self):
        first, *_ = self.line(**{"broken.txt": "target\n", "acme.txt": "target\n"})
        land.check_line(self.turn)
        land.check_line(self.turn)      # the second named red joins the first, one repair for both
        self.assertEqual((self.red()["tests"], len(self.prepared)), ([ACME, WIDGET], 1))
        failed = self.root / "failed-"  # what each helper piece failed, by its number

        def named(_away, shard, which="failed"):
            path = Path(f"{failed}{shard[0]}")
            return path.read_text().split() if which == "failed" and path.exists() else []

        piece = ["bash", "-c", f'AK_FAILED="{failed}${{AK_SHARD%/*}}"; {SUITE}']
        away = SimpleNamespace(alias="acme-helper", most=1, count=1)
        with patch.object(gate, "derived_heavy_limit", return_value=1), \
                patch.object(helper, "start", return_value=(away, "")), \
                patch.object(helper, "finish"), patch.object(helper, "piece", return_value=piece), \
                patch.object(helper, "failed", side_effect=named):
            land.check_line(self.turn)
        self.assertEqual(self.wait(first)["over"], [ACME, WIDGET])

    def test_a_red_that_named_no_test_holds_the_line_on_the_ladder(self):
        before = {directory: (directory / "run.json").read_bytes()
                  for directory in self.line(**{"crash.txt": "target breakage\n"})}
        land.check_line(self.turn)
        self.assertNotIn("tests", self.red())
        self.assertTrue(land.paused(self.red()))
        self.assert_parked(before)
        self.wake.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
