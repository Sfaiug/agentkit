"""A landing check whose red piece named its failed tests, and saw them fail again run alone,
names those tests on the red it hands the member (`fix["tests"]`); a red that needs its whole
piece, its tests passing alone, names none.

Offline: local Git, a shell suite that names its failed tests and runs only those asked for,
fake launches and wakes.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_landing_red_on_the_tip_pauses as red_tip
from agentkit import gate, land


def suite(red):
    """Piece 2/2 runs t_base then t_tax, piece 1/2 t_other; t_tax is red while `red` holds."""
    return ('if [ -n "$AK_ONLY" ]; then tests=$(cat "$AK_ONLY"); else case "$AK_SHARD" in '
            '2/*) tests="t_base t_tax";; *) tests=t_other;; esac; fi; code=0; '
            f'for t in $tests; do if [ "$t" = t_tax ] && {red}; then '
            'echo "$t" >> "${AK_FAILED:-/dev/null}"; code=1; fi; done; exit $code')


class RedStackNamesItsTests(unittest.TestCase):
    setUp = red_tip.RedOnTheTip.setUp
    prepare = red_tip.RedOnTheTip.prepare
    check = red_tip.RedOnTheTip.check
    member = red_tip.RedOnTheTip.member
    commit = red_tip.RedOnTheTip.commit
    advance = red_tip.RedOnTheTip.advance
    wait = red_tip.RedOnTheTip.wait
    declare = red_tip.RedOnTheTip.declare

    def red_of(self, red):
        self.declare(suite(red))
        member = self.member(**{"tax.txt": "the change\n"})
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        return self.wait(member)["fix"]

    def test_tests_failing_again_alone_are_named_on_the_red(self):
        fix = self.red_of("[ -f tax.txt ]")
        self.assertEqual((fix["piece"], fix.get("tests")), ("2/2", ["t_tax"]))

    def test_a_red_that_needs_its_whole_piece_names_none(self):
        fix = self.red_of('[ -f tax.txt ] && [ -z "$AK_ONLY" ]')
        self.assertEqual(fix["piece"], "2/2")
        self.assertNotIn("tests", fix)


if __name__ == "__main__":
    unittest.main()
