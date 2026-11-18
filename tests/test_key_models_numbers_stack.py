"""`ak models` counting in `% of a week` on 22 and 14 cells, where `quality  % of a week` and each
role's numbers side by side would pass the edge: each role's quality stands over its cost under
its model, the heading likewise, at one width; on 14 the unit and each model break at their
spaces as well.  Every line of them stays inside the edge, where the terminal would wrap it into
rows the page does not count.

Black-box: `AK_BIN` as `ak models`, in tests/test_key_models_role_lines.py's home, the unit kept
as `u` keeps it; judged by its output.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from test_key_models_answer import ENV, lines
import test_key_models_role_lines as role_lines

# On 14 cells, what breaks at its spaces into lines of the 10 cells four in leaves
BROKEN = {"% of a week": ["% of a", "week"], "Acme Bare 1 medium": ["Acme Bare", "1 medium"],
          "Acme Top 1 high": ["Acme Top 1", "high"], "Acme Plain 1": ["Acme Plain", "1"]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsNumbersStack(unittest.TestCase):
    def test_on_22_and_14_cells_each_roles_quality_stands_over_its_cost_inside_the_edge(self):
        home = role_lines.made(self.addCleanup)
        home.write(".agentkit/state/models-unit", "% of a week")
        printed = {width: home.ak("models", env={**ENV, "COLUMNS": str(width)})
                   for width in (100, 22, 14)}
        for done in printed.values():
            self.assertEqual(done.code, 0, done.err)
        numbers = {word: line.split()[-2:] for line in role_lines.said(printed[100].out)
                   for word, *_ in role_lines.NEW_SEATS.values() if word in line.split()}
        for width, broken in ((22, {}), (14, BROKEN)):
            shown = lines(printed[width].out)
            first = next(n for n, line in enumerate(shown) if line.split() == ["quality"])
            shown = shown[first:shown.index("", first)]
            self.assertLessEqual(max(map(len, shown)), width, shown)
            self.assertEqual([" ".join(line.split()) for line in shown], [
                "quality", *broken.get("% of a week", ["% of a week"]),
                *(line for word, model, *_ in role_lines.NEW_SEATS.values()
                  for line in [word, *broken.get(model, [model]), *numbers[word]])], width)


if __name__ == "__main__":
    unittest.main()
