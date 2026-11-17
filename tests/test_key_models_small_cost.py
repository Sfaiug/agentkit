"""A cost above 0 that two decimals would say as `0.00` is said to its first figure that is not
0, rounded there, `≈` before it where no run measured it, every other cost as before: on
`r recommended` on `c`, at 100 cells and at 40, a review that cost $0.004 reads `$0.004` on its
bar and on its why, never `$0.00`, and after `u`, at 0.0013% of its plan's week, `0.001%`.

Black-box: `AK_BIN` in a terminal (tests/fixtures/akterm.py), the boards, harness and [defaults]
of tests/test_key_models_bars.py on a plan (test_key_models_unit_switch.planned) whose week a
review of Acme Base 1 measured (test_key_role_cost_from_runs's History); judged by the screen.
Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, lines
from test_key_models_bars import bars
from test_key_models_unit_switch import planned

# $1300 a month, so a week of it $300 and a point of that $3, a point being 1.5 million tokens:
# Base reviews in 2,000 of them, 0.0013 points, $0.004, and every row no run measures costs what
# a board dollar of that review does, $0.002 and 0.00067 points.  Per unit, the costs on the
# reviewer's bars, left to right (test_key_models_bars.BARS): Base, Long Name, Step, Dear and
# Top, $2 to $8 on the boards, from half a cent on in two decimals
COSTS = {"$ a task": ["$0.004", "≈$0.01", "≈$0.01", "≈$0.01", "≈$0.02"],
         "% of a week": ["0.001%", "≈0.002%", "≈0.003%", "≈0.004%", "≈0.01%"]}
# and what its why's cost says
WHY = {"$ a task": "$0.004 a review", "% of a week": "0.001% of a week a review"}
FREE = re.compile(r"\$0\.00(?!\d)|(?<![\d.])0\.00%")      # a cost two decimals say as nothing


def costs(screen):
    """The costs on the reviewer's bars, left to right; None before they are drawn."""
    try:
        return [bar["cost"] for bar in bars(screen, "reviewer")]
    except (StopIteration, ValueError, IndexError):
        return None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsSmallCost(unittest.TestCase):
    def models(self, width):
        """`r` on `c` in a window of its own, 60 rows high, of a Home of its own, as the screen
        opens in the unit last chosen, once it is drawn."""
        home = Home()
        self.addCleanup(home.close)
        history = planned(home, 1300)
        history.week("anthropic", "default", "claude", "acme-base-1", 75e6, 50)
        history.run(None, "base", ["high"],
                    reviewed=[[("default", "acme-base-1", (2000, 0, 0, 0))]])
        history.save()
        term = Terminal(home, size=(width, 60), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("\n› orchestrator ")
        return term

    def test_a_cost_under_half_a_cent_reads_its_first_figure_on_its_bar_and_its_why(self):
        for width in (100, 40):
            with self.subTest(width=width):
                term = self.models(width)
                for keys, unit in ((["Down", "Down"], "$ a task"), (["u"], "% of a week")):
                    term.keys(*keys)
                    term.wait(lambda screen: costs(screen) == COSTS[unit]
                              and not FREE.search(screen))
                    term.keys("Enter")
                    # drawn whole once its key line, the last, stands under its cost
                    term.wait(lambda screen: lines(screen.rstrip())[-1] == "  esc back"
                              and f"\n  cost       {WHY[unit]}" in screen
                              and not FREE.search(screen))
                    term.keys("Escape")
                    term.wait("\n› reviewer ")


if __name__ == "__main__":
    unittest.main()
