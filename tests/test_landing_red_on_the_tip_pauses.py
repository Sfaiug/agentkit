"""A red landing piece runs again on the target's tip alone before anyone is blamed.

Red there pauses the line on the retry ladder: nobody is woken, no repair starts, and at each
step the piece runs there again; green there is the change's own red and goes to its fixer,
whatever pass the target has on record; red through the whole ladder is the target's own and
gets its one repair as before.  Offline: local Git, the fixture's shell suites, fake launches
and wakes, a stopped clock.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import ANY, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander as fixture
import test_lander_red_main as red_main
from agentkit import config, gate, land, record, run

FLAKY = "test ! -f ../flake"     # red on every checkout while the host holds the flag


class RedOnTheTip(unittest.TestCase):
    setUp = red_main.RedMain.setUp
    prepare = red_main.RedMain.prepare
    member = red_main.RedMain.member
    assert_parked = red_main.RedMain.assert_parked
    commit = fixture.Lander.commit
    advance = fixture.Lander.advance
    check = fixture.Lander.check
    wait = fixture.Lander.wait
    assert_cleaned = fixture.Lander.assert_cleaned

    def declare(self, suite):
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n")
        self.commit("declare the suite")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")

    def flag(self):
        config.WT.mkdir(parents=True, exist_ok=True)
        flake = config.WT / "flake"
        flake.write_text("the host is in no state to run a suite\n")
        return flake

    def clock(self, now=1_000_000):
        held = [now]
        patcher = patch.object(land.time, "time", side_effect=lambda: held[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        return held

    def red(self):
        tree = run.git(self.repo, "rev-parse", "origin/main^{tree}")
        return land._trees(self.turn, "red")[1].get(tree)

    def commands(self):
        return [cmds for cmds, _, _ in self.checks]

    def test_red_on_the_tip_alone_pauses_the_line_until_the_ladder_says_again(self):
        self.declare(FLAKY)
        first, later = self.member(), self.member("later", joined=2)
        self.advance()
        flake = self.flag()
        held = self.clock()
        before = {d: (d / "run.json").read_bytes() for d in (first, later)}
        said = []
        land.check_line(self.turn, said.append)
        self.assertEqual(self.commands(), [["true", FLAKY], [FLAKY]])
        self.assert_parked(before)
        self.wake.assert_not_called()
        self.assertEqual(self.prepared, [])
        self.assertEqual((self.red()["probes"], self.red()["probe"]["piece"]), (1, ""))
        self.assertIn("Tree: ", (first / "target-probe.log").read_text())
        self.assertIn("fails its suite alone: the line waits, nobody is blamed; probed again in 1 min",
                      said[-1])
        # not due yet: a pass does nothing
        land.check_line(self.turn, said.append)
        self.assertEqual(len(self.checks), 2)
        # due: the piece alone runs on the tip, still red, and the next step is longer
        held[0] += run.TRANSIENT_BACKOFF[0]
        land.check_line(self.turn, said.append)
        self.assertEqual(self.commands()[2:], [[FLAKY]])
        self.assertEqual(self.red()["probes"], 2)
        self.assert_parked(before)
        self.wake.assert_not_called()
        self.assertIn("probed again in 5 min", said[-1])
        # the host recovers: the piece passes on the tip, the stack is checked and lands
        flake.unlink()
        held[0] += run.TRANSIENT_BACKOFF[1]
        land.check_line(self.turn, said.append)
        self.assertEqual(self.commands()[3:], [[FLAKY], ["true", FLAKY]])
        self.assertIsNone(self.red())
        self.assertEqual(self.wait(later)["land"], self.wait(first)["land"])
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assertEqual(self.prepared, [])
        self.assert_cleaned()

    def test_a_sharded_suites_red_piece_alone_runs_on_the_tip(self):
        suite = 'case "$AK_SHARD" in 2/*) test ! -f ../flake;; *) true;; esac'
        self.declare(suite)
        first = self.member()
        self.advance()
        self.flag()
        self.clock()
        said = []
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn, said.append)
        piece = gate.piece_command("2/2", suite)
        self.assertFalse(gate.names_shard(piece))
        self.assertEqual(self.commands(), [["true", suite], [piece]])
        self.assertEqual(self.red()["probe"]["piece"], "2/2")
        self.assertIn(f"$ {piece}\n[exit 1]", (first / "target-probe.log").read_text())
        self.assertIn(f"`{suite}`, its piece AK_SHARD=2/2, fails on origin/main at",
                      self.red()["probe"]["text"])
        self.assertIn("fails its piece AK_SHARD=2/2 alone", said[-1])
        self.wake.assert_not_called()
        self.assertEqual(self.prepared, [])

    def test_red_through_the_ladder_is_the_targets_own_and_gets_its_repair(self):
        self.declare(FLAKY)
        self.member()
        self.advance()
        self.flag()
        held = self.clock()
        land.check_line(self.turn)
        for step in range(1, len(run.TRANSIENT_BACKOFF) + 1):
            held[0] += run.transient_delay(step)
            land.check_line(self.turn)
            self.assertEqual(self.red()["probes"], step + 1)
        self.assertEqual(len(self.checks), 2 + len(run.TRANSIENT_BACKOFF))
        self.assertEqual(len(self.prepared), 1)
        directory, opts = self.prepared[0]
        self.assertTrue(opts["--first"])
        repair = record.read_state(directory)
        self.assertEqual(repair["repair"], {"target": "main", "command": FLAKY})
        self.assertIn("target's own tip", (directory / "task.md").read_text())
        self.assertEqual(self.red()["run"], directory.name)
        self.wake.assert_not_called()
        land.check_line(self.turn)       # the repair holds the line from here, as before
        self.assertEqual(len(self.checks), 2 + len(run.TRANSIENT_BACKOFF))
        self.assertEqual(len(self.prepared), 1)

    def test_green_on_the_tip_is_the_members_own_red_whatever_pass_the_target_has(self):
        first = self.member(**{"broken.txt": "branch breakage\n"})
        self.advance()
        run.fetch(self.repo, "origin")
        land.note(self.turn, [run.git(self.repo, "rev-parse", "origin/main^{tree}")], "earlier",
                  checks=[red_main.SUITE])
        land.check_line(self.turn)
        self.assertEqual(self.commands(), [["true", red_main.SUITE], [red_main.SUITE]])
        self.assertIn(red_main.SUITE, self.wait(first)["fix"]["line"])
        self.wake.assert_called_once_with(first.name, ANY)
        self.assertIsNone(self.red())
        self.assertEqual(self.prepared, [])

    def test_a_red_check_of_the_members_own_runs_no_probe(self):
        first = fixture.Lander.member(self, "first", 1, once="test -f absent.txt")
        self.advance()
        land.check_line(self.turn)
        self.assertEqual(self.commands(), [["test -f absent.txt", red_main.SUITE]])
        self.assertIn("test -f absent.txt", self.wait(first)["fix"]["line"])
        self.assertFalse((first / "target-probe.log").exists())
        self.assertIsNone(self.red())

    def test_a_killed_piece_runs_the_suite_whole_on_the_tip(self):
        # piece 1 talks and passes, piece 2 goes silent while the host holds the flag: its
        # kill stops piece 1 too, recorded alike, so no log tells which piece hung
        suite = ('case "$AK_SHARD" in 1/*) for i in 1 2 3 4 5 6; do echo tick; sleep 1; done;; '
                 '*) if test -f ../flake; then sleep 30; fi;; esac')
        self.declare(suite)
        first = self.member()
        with record.record(first) as state:
            state["silence_minutes"] = 0.05
        self.advance()
        self.flag()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertEqual(self.commands(), [["true", suite], [suite]])
        self.assertEqual(self.red()["probe"]["piece"], "")
        self.wake.assert_not_called()

    def test_a_target_suite_that_changes_its_checkout_blames_no_member(self):
        self.declare("printf more >> base.txt")
        self.member()
        self.advance()
        land.check_line(self.turn)
        self.assertEqual(self.red()["probes"], 1)
        self.wake.assert_not_called()

    def test_with_no_suite_a_check_that_changes_its_checkout_is_the_members(self):
        (self.repo / "AGENTS.md").write_text("# acme\n")
        self.commit("no declared suite")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        first = fixture.Lander.member(self, "first", 1, once="printf changed >> work.txt")
        self.advance()
        land.check_line(self.turn)
        self.assertIn("Checkout changed during", self.wait(first)["fix"]["line"])
        self.wake.assert_called_once_with(first.name, ANY)
        self.assertIsNone(self.red())

    def test_a_red_entry_an_earlier_lander_kept_is_the_targets_own(self):
        self.member()
        self.advance(**{"broken.txt": "target breakage\n"})
        run.fetch(self.repo, "origin")
        tip = run.git(self.repo, "rev-parse", "origin/main")
        land.note(self.turn, [], "earlier", red={
            run.git(self.repo, "rev-parse", "origin/main^{tree}"): {"probe": {
                "command": red_main.SUITE, "check": f"{red_main.SUITE}  # once", "sha": tip,
                "text": "fails"}}})
        land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(self.checks, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
