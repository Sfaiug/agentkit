"""A red landing piece runs again on the target's tip alone before anyone is blamed.

Red there pauses the line on the retry ladder: nobody is woken, no repair starts, and at each
step the piece runs there again; green there is the change's own red and goes to its fixer,
whatever pass the target has on record; red through the whole ladder is the target's own and
gets its one repair as before.  A piece that named the tests failing it, red again alone, has
those alone run there first where the tip holds each: passing, the red is the member's own;
failing, which proves nothing, the piece runs.  Offline: local Git, the fixture's shell
suites, fake launches and wakes, a stopped clock.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import ANY, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander as fixture
import test_lander_red_main as red_main
from agentkit import config, gate, land, record, run, turns

FLAKY = "test ! -f ../flake"     # red on every checkout while the host holds the flag
# Piece 2/2 runs each test_*.sh, or just those AK_ONLY lists, naming each that fails; 1/2 none.
# A listed name it does not hold runs nothing and fails nothing, as agentkit's own suite does.
NAMING = ('if [ -n "$AK_ONLY" ]; then tests=$(cat "$AK_ONLY"); else case "$AK_SHARD" in '
          '2/*) tests=$(ls test_*.sh);; *) tests=;; esac; fi; code=0; for t in $tests; do '
          '[ -f "$t" ] || continue; '
          'bash "$t" || { echo "$t" >> "${AK_FAILED:-/dev/null}"; code=1; }; done; exit $code')


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

    def probes(self):
        return [(kw["shard"], kw.get("only")) for _, _, kw in self.checks if kw.get("shard")]

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
        held[0] += turns.TRANSIENT_BACKOFF[0]
        land.check_line(self.turn, said.append)
        self.assertEqual(self.commands()[2:], [[FLAKY]])
        self.assertEqual(self.red()["probes"], 2)
        self.assert_parked(before)
        self.wake.assert_not_called()
        self.assertIn("probed again in 5 min", said[-1])
        # the host recovers: the piece passes on the tip, the stack is checked and lands
        flake.unlink()
        held[0] += turns.TRANSIENT_BACKOFF[1]
        land.check_line(self.turn, said.append)
        self.assertEqual(self.commands()[3:], [[FLAKY], ["true", FLAKY]])
        self.assertIsNone(self.red())
        self.assertEqual(self.wait(later)["land"], self.wait(first)["land"])
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assertEqual(self.prepared, [])
        self.assert_cleaned()

    def test_a_pause_lifted_by_a_green_probe_runs_no_second_probe_for_the_members_own_red(self):
        suite = f"{FLAKY} && test ! -f broken.txt"
        self.declare(suite)
        first = self.member(**{"broken.txt": "the branch's own breakage\n"})
        self.advance()
        flake = self.flag()
        held = self.clock()
        land.check_line(self.turn)          # red on the tip alone: the line pauses
        self.assertEqual(self.commands(), [["true", suite], [suite]])
        flake.unlink()
        held[0] += turns.TRANSIENT_BACKOFF[0]
        land.check_line(self.turn)          # the piece passes on the tip; the stack is red by its own
        self.assertEqual(self.commands()[2:], [[suite], ["true", suite]])
        self.assertIn(suite, self.wait(first)["fix"]["line"])
        self.wake.assert_called_once_with(first.name, ANY)
        self.assertIsNone(self.red())

    def test_a_sharded_suites_red_piece_alone_runs_on_the_tip(self):
        suite = 'case "$AK_SHARD" in 2/*) echo piece-two-broke; test ! -f ../flake;; *) true;; esac'
        self.declare(suite)
        first = self.member()
        self.advance()
        self.flag()
        self.clock()
        said = []
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn, said.append)
        # the probe is the suite run as that one piece, its share set by the runner, never a
        # command of its own: a project's suite line may set AK_SHARD itself and still be split
        self.assertEqual(self.commands(), [["true", suite], [suite]])
        self.assertEqual(self.checks[-1][2].get("shard"), "2/2")
        self.assertTrue(gate.names_shard("export AK_SHARD=${AK_SHARD:-1/1}; make test"))
        self.assertEqual(self.red()["probe"]["piece"], "2/2")
        # what the piece printed on the tip is what a repair or a PR's fixer is told
        shown = f"$ {suite}\n[exit 1]\n--- AK_SHARD=2/2 ---\npiece-two-broke"
        self.assertIn(shown, (first / "target-probe.log").read_text())
        self.assertIn(f"`{suite}`, its piece AK_SHARD=2/2, fails on origin/main at",
                      self.red()["probe"]["text"])
        self.assertIn(shown.replace("\n", "\n    "), self.red()["probe"]["text"])
        self.assertIn("fails its piece AK_SHARD=2/2 alone", said[-1])
        self.wake.assert_not_called()
        self.assertEqual(self.prepared, [])

    def test_a_piece_failing_once_by_chance_on_the_tip_runs_again(self):
        # piece 2 fails on the member every time, and on the tip only its first run
        suite = ('case "$AK_SHARD" in 2/*) test ! -f broken.txt && '
                 '{ test -f ../once || { touch ../once; false; }; };; *) true;; esac')
        self.declare(suite)
        first = self.member(**{"broken.txt": "own\n"})
        self.advance()
        self.clock()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertEqual(self.checks[-1][2].get("shard"), "2/2")
        self.assertIsNone(self.red())
        self.assertIn("flaky:", (first / "target-probe.log").read_text())
        self.wake.assert_called_once_with(first.name, ANY)

    def own_red(self, change):
        """The tip's probes, as (piece, tests), for a member whose `change` fails the tests its
        piece names on a tip where test_tax.sh passes: the red its own, woken with them."""
        (self.repo / "test_tax.sh").write_text("exit 0\n")
        self.declare(NAMING)
        first = self.member(**change)
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertEqual(self.wait(first)["fix"]["tests"], list(change))
        self.wake.assert_called_once_with(first.name, ANY)
        self.assertIsNone(self.red())
        return self.probes()

    def test_the_failed_tests_passing_alone_on_the_tip_make_the_red_the_members(self):
        self.assertEqual(self.own_red({"test_tax.sh": "exit 1\n"}), [("2/2", ["test_tax.sh"])])

    def test_a_test_the_member_added_leaves_the_tip_to_its_whole_piece(self):
        self.assertEqual(self.own_red({"test_new.sh": "exit 1\n"}), [("2/2", None)])

    def test_the_failed_tests_red_on_the_tip_too_leave_the_whole_piece_to_decide(self):
        self.declare(NAMING)
        first = self.member()
        self.advance(**{"test_tax.sh": "exit 1\n"})
        held = self.clock()
        before = (first / "run.json").read_bytes()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
            self.assertEqual(self.probes(), [("2/2", ["test_tax.sh"]), ("2/2", None)])
            self.assertNotIn("tests", self.red()["probe"])
            self.assert_parked({first: before})
            held[0] += turns.TRANSIENT_BACKOFF[0]
            land.check_line(self.turn)      # the ladder runs the piece itself
        self.assertEqual(self.probes()[2:], [("2/2", None)])
        self.assertEqual(self.red()["probes"], 2)
        self.wake.assert_not_called()

    def test_the_red_piece_is_read_from_its_exit_never_from_what_a_piece_printed(self):
        # piece 1 prints a red piece's record lines and passes; piece 2 fails on every checkout
        suite = 'case "$AK_SHARD" in 1/*) echo "--- AK_SHARD=1/2 ---"; echo "[exit 1]";; *) test ! -f ../flake;; esac'
        self.declare(suite)
        self.member()
        self.advance()
        self.flag()
        self.clock()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertEqual(self.checks[-1][2].get("shard"), "2/2")
        self.assertEqual(self.red()["probe"]["piece"], "2/2")
        self.wake.assert_not_called()
        self.assertEqual(self.prepared, [])

    def test_a_piece_killed_by_a_signal_is_the_red_piece(self):
        suite = 'case "$AK_SHARD" in 2/*) kill -9 $$;; *) true;; esac'
        self.declare(suite)
        self.member()
        self.advance()
        self.clock()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertEqual(self.checks[-1][2].get("shard"), "2/2")
        self.assertEqual(self.red()["probe"]["piece"], "2/2")
        self.wake.assert_not_called()

    def test_red_through_the_ladder_is_the_targets_own_and_gets_its_repair(self):
        self.declare(FLAKY)
        self.member()
        self.advance()
        self.flag()
        held = self.clock()
        land.check_line(self.turn)
        for step in range(1, len(turns.TRANSIENT_BACKOFF) + 1):
            held[0] += turns.transient_delay(step)
            land.check_line(self.turn)
            self.assertEqual(self.red()["probes"], step + 1)
        self.assertEqual(len(self.checks), 2 + len(turns.TRANSIENT_BACKOFF))
        self.assertEqual(len(self.prepared), 1)
        directory, opts = self.prepared[0]
        self.assertTrue(opts["--first"])
        repair = record.read_state(directory)
        self.assertEqual(repair["repair"], {"target": "main", "command": FLAKY})
        self.assertIn("target's own tip", (directory / "task.md").read_text())
        self.assertEqual(self.red()["run"], directory.name)
        self.wake.assert_not_called()
        land.check_line(self.turn)       # the repair holds the line from here, as before
        self.assertEqual(len(self.checks), 2 + len(turns.TRANSIENT_BACKOFF))
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

    def killed(self, piece):
        """Piece 2 goes silent while the host holds the flag and is killed; its kill stops
        `piece` 1 too, never retried: the suite whole runs on the tip and nobody is woken."""
        suite = f'case "$AK_SHARD" in 1/*) {piece};; *) if test -f ../flake; then sleep 30; fi;; esac'
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

    def test_a_killed_piece_runs_the_suite_whole_on_the_tip(self):
        # piece 1 talks and passes, stopped by the kill and recorded alike
        self.killed("for i in 1 2 3 4 5 6; do echo tick; sleep 1; done")

    def test_a_red_piece_beside_a_killed_one_runs_the_suite_whole_on_the_tip(self):
        # piece 1 fails its first run only, a flake the kill leaves unretried
        self.killed("test -f ../ran1 || { touch ../ran1; exit 1; }")

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
