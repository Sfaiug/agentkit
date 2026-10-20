"""The models screen says why its recommendation is the one.  Above the table, each row with
its quality for the role and what Artificial Analysis's index run cost it, by its full name
(`Opus 5.5 @ max 100 $8000`): `best`, the row of the highest quality per role (matrix.tops), `as good`, the rows
within the knob of it, cheapest first, and `recommended`, said as the cheapest as good; a row
Artificial Analysis has not run is said without a cost and sorts after every priced one.

Offline, on test_models_screen's fixture: a throwaway HOME, rows written by hand, the keys fed in.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit.terminal import Key
import test_models_screen as screen


class SaysWhy(screen.Screen):
    def test_the_best_the_rows_as_good_and_the_recommended_each_carry_quality_and_cost(self):
        text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
        # opus at max is the best in every role; its xhigh is as good at half the cost; astra,
        # as good at a tenth of it, is the cheapest as good to build and review
        opus, astra = self.opus, self.astra
        self.assertIn(f"best orch {opus} @ max 100 $8000 · builds {opus} @ max 100 $8000 · reviews "
                      f"{opus} @ max 100 $8000 as good builds {opus} @ xhigh 97 $4000 · reviews {opus} "
                      f"@ xhigh 97 $4000 recommended the cheapest as good: orch {opus} @ xhigh 97 $4000 "
                      f"· builds {astra} @ xhigh 95 $500 · reviews {astra} @ xhigh 96 $500", text)

    def test_a_row_without_an_index_run_cost_is_said_without_one_after_every_priced_row(self):
        rows = [screen.row("claude", "claude-opus-5-5", "max", 100, 100, 100, cost=8000),
                screen.row("claude", "claude-opus-5-5", "xhigh", 96.55, 96.55, 96.55, cost=4000),
                # Artificial Analysis has not run astra
                screen.row("codex", "gpt-6-astra", "xhigh", 84.64, 95.48, 95.75)]
        self.store(rows)
        text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
        opus, astra = self.opus, self.astra
        self.assertIn(f"as good builds {astra} @ xhigh 95 · reviews {astra} @ xhigh 96 recommended the "
                      f"cheapest as good: orch {opus} @ xhigh 97 $4000 · builds {opus} @ xhigh 97 $4000 "
                      f"· reviews {opus} @ xhigh 97 $4000", text)


if __name__ == "__main__":
    unittest.main()
