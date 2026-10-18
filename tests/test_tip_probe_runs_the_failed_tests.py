"""A first stack red on tests its piece named, failing again run alone, has just those tests run
on the target's tip alone before anyone is blamed: passing there, the same tests alone on both
trees make the red the member's, in a fraction of the piece's time.  Failing there, as one the
member added does, they keep a pause going at each step of the ladder, but the whole piece
decides whether one begins or a repair starts, as it does for a red only the whole piece shows.

Offline: local Git, the fixture's shell suite as a runner that names its failed tests and runs
only those asked for, fake launches and wakes, a stopped clock.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import ANY, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_landing_red_on_the_tip_pauses as red_tip
from agentkit import gate, land, turns


def suite(fails):
    """Piece 2/2 runs t_total then t_tax, piece 1/2 t_fine; t_tax fails while `fails` holds."""
    return ('if [ -n "$AK_ONLY" ]; then tests=$(cat "$AK_ONLY"); else case "$AK_SHARD" in '
            '2/*) tests="t_total t_tax";; *) tests=t_fine;; esac; fi; code=0; '
            f'for t in $tests; do if [ "$t" = t_tax ] && {fails}; then echo "FAIL $t"; '
            'echo "$t" >> "${AK_FAILED:-/dev/null}"; code=1; else echo "PASS $t"; fi; done; '
            'exit $code')


BROKEN = suite("[ -f broken.txt ]")
NEEDS_ITS_PIECE = suite('[ -f broken.txt ] && [ -z "$AK_ONLY" ]')
# Piece 2/2 runs each t_* file; a runner asked for one a tree lacks fails on it.
FILES = ('if [ -n "$AK_ONLY" ]; then tests=$(cat "$AK_ONLY"); else case "$AK_SHARD" in '
         '2/*) tests=$(ls t_*);; *) tests=;; esac; fi; code=0; '
         'for t in $tests; do bash "$t" || { echo "$t" >> "${AK_FAILED:-/dev/null}"; code=1; }; '
         'done; exit $code')


class TipProbeRunsTheFailedTests(unittest.TestCase):
    setUp = red_tip.RedOnTheTip.setUp
    prepare = red_tip.RedOnTheTip.prepare
    check = red_tip.RedOnTheTip.check
    member = red_tip.RedOnTheTip.member
    assert_parked = red_tip.RedOnTheTip.assert_parked
    commit = red_tip.RedOnTheTip.commit
    advance = red_tip.RedOnTheTip.advance
    wait = red_tip.RedOnTheTip.wait
    declare = red_tip.RedOnTheTip.declare
    clock = red_tip.RedOnTheTip.clock
    flag = red_tip.RedOnTheTip.flag
    red = red_tip.RedOnTheTip.red

    def probes(self):
        """(share, tests) of each check run as one piece: the tip probes."""
        return [(kw["shard"], kw.get("only")) for _, _, kw in self.checks if kw.get("shard")]

    def check_line(self, said=None):
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn, (said if said is not None else []).append)

    def test_the_tests_red_again_alone_pass_on_the_tip_so_the_red_is_the_members(self):
        self.declare(BROKEN)
        first = self.member(**{"broken.txt": "the branch's own breakage\n"})
        self.advance()
        self.clock()
        self.check_line()
        self.assertEqual(self.probes(), [("2/2", ["t_tax"])])
        probe = (first / "target-probe.log").read_text()
        self.assertIn("--- AK_SHARD=2/2, its failed tests alone ---\nPASS t_tax", probe)
        self.assertNotIn("PASS t_total", probe)
        fix = self.wait(first)["fix"]
        self.assertEqual((fix["piece"], fix["tests"]), ("2/2", ["t_tax"]))
        self.assertIn("its failed tests failed again, run alone", Path(fix["log"]).read_text())
        self.wake.assert_called_once_with(first.name, ANY)
        self.assertIsNone(self.red())

    def test_the_tests_red_on_the_tip_too_pause_the_line_and_run_again_on_the_ladder(self):
        self.declare(BROKEN)
        first = self.member()
        self.advance(**{"broken.txt": "target breakage\n"})
        held = self.clock()
        before = (first / "run.json").read_bytes()
        said = []
        self.check_line(said)
        self.assertEqual(self.probes(), [("2/2", ["t_tax"]), ("2/2", None)])
        self.assertEqual((self.red()["probe"]["piece"], self.red()["probe"]["tests"]),
                         ("2/2", ["t_tax"]))
        self.assertIn("fails its piece AK_SHARD=2/2 alone: the line waits, nobody is blamed; "
                      "probed again in 1 min", said[-1])
        self.assert_parked({first: before})
        self.wake.assert_not_called()
        held[0] += turns.TRANSIENT_BACKOFF[0]
        self.check_line(said)
        self.assertEqual(self.probes()[2:], [("2/2", ["t_tax"])])
        self.assertEqual(self.red()["probes"], 2)
        self.assertIn("fails the failed tests of its piece AK_SHARD=2/2 alone", said[-1])
        self.wake.assert_not_called()

    def test_a_red_of_the_tests_alone_starts_no_repair_once_the_whole_piece_passes(self):
        (self.repo / "t_total").write_text("test ! -f ../flake\n")
        self.declare(FILES)
        first = self.member(t_new="exit 1\n")
        self.advance()
        flake = self.flag()
        held = self.clock()
        self.check_line()           # the host fails the whole piece too: the line pauses
        self.assertEqual(self.probes(), [("2/2", ["t_new", "t_total"]), ("2/2", None)])
        flake.unlink()
        for delay in turns.TRANSIENT_BACKOFF:
            held[0] += delay
            self.check_line()
        # t_new, which the tip lacks, keeps the pause, and the last step's whole piece ends it
        self.assertEqual(self.probes()[2:], [("2/2", ["t_new", "t_total"])] * 5 + [("2/2", None)])
        self.assertEqual(self.prepared, [])
        self.assertIsNone(self.red())
        self.assertEqual(self.wait(first)["fix"]["tests"], ["t_new"])
        self.wake.assert_called_once_with(first.name, ANY)

    def test_a_failing_test_the_member_added_is_the_members_whatever_the_tip_lacks(self):
        (self.repo / "t_total").write_text("exit 0\n")
        self.declare(FILES)
        first = self.member(t_new="exit 1\n")
        self.advance()
        self.clock()
        self.check_line()
        self.assertEqual(self.probes(), [("2/2", ["t_new"]), ("2/2", None)])
        self.assertEqual(self.wait(first)["fix"]["tests"], ["t_new"])
        self.wake.assert_called_once_with(first.name, ANY)
        self.assertIsNone(self.red())

    def test_a_red_only_its_whole_piece_shows_probes_the_whole_piece(self):
        self.declare(NEEDS_ITS_PIECE)
        first = self.member(**{"broken.txt": "the branch's own breakage\n"})
        self.advance()
        self.clock()
        self.check_line()
        self.assertEqual(self.probes(), [("2/2", None)])
        fix = self.wait(first)["fix"]
        self.assertEqual(fix["piece"], "2/2")
        self.assertNotIn("tests", fix)
        self.wake.assert_called_once_with(first.name, ANY)


if __name__ == "__main__":
    unittest.main()
