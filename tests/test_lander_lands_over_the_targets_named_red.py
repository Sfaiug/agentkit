"""The lander lands over a target's named red while its repair is under way, in detail beside
tests/test_key_a_targets_own_red_does_not_hold_its_line.py: merges, prompts and every probe.

The tip fails tests/test_widget.py alone, by name: stacks red in nothing else land over it, on
helper pieces too, unproven and with no trailer; one red in another test gets a fix naming that
alone, its fixer told of the target's even where the fix came first, and one the tip cannot name
is the member's where the tip, run whole, fails nothing else.  The repair lands once its stack
passes the test, or is the culprit, a stack of one tree with it answered apart; a member behind
it red in that test waits for it, as on the tip alone the target's red fails that test whoever
stands there.  Offline: the lander fixture, a shell suite, fake launches, wakes and helper,
merges by a push.
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

WIDGET, ACME, BETA = "tests/test_widget.py", "tests/test_acme.py", "tests/test_beta.py"
# The suite fails naming nothing where crash.txt is; otherwise piece k/n runs every nth test from
# the kth, test_acme.py in 1/2 and test_widget.py in 2/2, or those AK_ONLY lists, naming each.
SUITE = ('test ! -f crash.txt || exit 1; code=0; for t in $(cat "$AK_ONLY" 2>/dev/null || ls '
         'tests/test_*.py | sed -n "${AK_SHARD%/*}~${AK_SHARD#*/}p"); do [ -f "$t" ] || continue; '
         'echo "$t" >>"${AK_RAN:-/dev/null}"; python3 "$t" || { code=1; '
         'echo "$t" >>"${AK_FAILED:-/dev/null}"; }; done; exit $code')


class LandsOverTheTargetsNamedRed(unittest.TestCase):
    setUp = red_main.RedMain.setUp
    prepare = red_main.RedMain.prepare
    member = red_main.RedMain.member
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

    def assert_told(self, directory):
        """`directory`'s fix is for test_acme.py, its own, and its landing fixer is told the
        target itself fails test_widget.py (`prompts.excused`)."""
        fix = self.wait(directory)["fix"]
        self.assertEqual((fix["tests"], fix["excused"]), ([ACME], [WIDGET]))
        lp = SimpleNamespace(state=record.read_state(directory), run_dir=directory)
        with patch.object(roundloop, "execute", side_effect=StopIteration) as fixer, \
                self.assertRaises(StopIteration):
            roundloop.landing_fixer(lp, "", "final-fixer")
        self.assertIn(f"The target itself fails {WIDGET}: not this run's to mend.",
                      fixer.call_args.args[2])

    def test_a_fix_given_before_the_red_was_found_is_told_of_it(self):
        first, second, third = self.line()
        land.check_line(self.turn)      # the target green: the third's own red, behind the two
        self.assertEqual(self.wait(third)["fix"]["tests"], [ACME])
        self.advance(**{"broken.txt": "target breakage\n"})
        for directory in (first, second):   # each delivery meets the moved target and rejoins
            with record.record(directory) as state:     # (`deliver.rejoin_line`)
                state["waiting_on"] = {key: state["waiting_on"][key] for key in ("line", "joined")}
        land.check_line(self.turn)
        self.assertEqual(self.red()["tests"], [WIDGET])
        self.assert_told(third)

    def test_a_stack_red_only_in_the_targets_named_red_lands_over_it_unproven(self):
        first, second, third = self.line(**{"broken.txt": "target breakage\n"})
        land.check_line(self.turn)
        # the first stack's red repeats on the tip alone, by name: the target's, repaired at once
        repair = self.prepared[0][0]
        self.assertEqual((self.red()["tests"], self.red()["run"]), ([WIDGET], repair.name))
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
        self.assert_told(third)
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

    def test_a_member_red_in_the_targets_red_behind_its_repair_waits_for_the_repair(self):
        # on the tip alone the target's red fails that test, whoever stands there: it proves
        # nothing of the member, which waits for the repair under it to land
        self.line(**{"broken.txt": "target breakage\n"})
        land.check_line(self.turn)
        repair = self.prepared[0][0]
        self.ready_repair(repair)
        worse = self.member("worse", 101, **{"worse.txt": "worse\n"})
        land.check_line(self.turn)
        wait = self.wait(worse)
        self.assertEqual(wait["fix"]["tests"], [WIDGET])
        self.assertIn(repair.name, wait["after"])

    def first_in_line(self, **files):
        """The fix of a member first in line adding `files` beside the target's named red: the
        tip, run whole, fails nothing but that red, and the members behind it land over it."""
        first, second, _ = self.line(**{"broken.txt": "target breakage\n"})
        land.check_line(self.turn)
        red = self.member("red", 0.5, **files)
        land.check_line(self.turn)
        self.assertEqual(self.red()["tests"], [WIDGET])
        self.assertEqual([self.wait(member)["over"] for member in (first, second)],
                         [[WIDGET]] * 2)
        return self.wait(red)["fix"]

    def test_a_member_red_naming_no_test_beside_the_targets_named_red_is_its_own(self):
        fix = self.first_in_line(**{"crash.txt": "crash\n"})
        self.assertEqual((fix.get("tests"), fix["excused"]), (None, [WIDGET]))

    def test_a_member_red_in_a_test_the_tip_lacks_beside_the_targets_named_red_is_its_own(self):
        fix = self.first_in_line(**{BETA: "raise SystemExit(1)\n"})
        self.assertEqual((fix["tests"], fix["excused"]), ([BETA], [WIDGET]))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
