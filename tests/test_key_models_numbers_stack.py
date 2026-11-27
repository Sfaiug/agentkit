"""`r recommended` on `c` counting in `% of a week` on 22 and 14 cells, where `quality  % of a
week` and each role's numbers side by side would pass the edge: each role's quality stands over
its cost under its model, the heading likewise, at one width; on 14 the unit and each model break
at their spaces as well.  Every line of them stays inside the edge, where the terminal would wrap
it into rows the page does not count.

Black-box: `AK_BIN` in a terminal (tests/fixtures/akterm.py), in
tests/test_key_models_role_lines.py's home, the unit kept as `u` keeps it; judged by the screen.
Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, lines
import test_key_models_role_lines as role_lines

# On 14 cells, what breaks at its spaces into lines of the 10 cells four in leaves
BROKEN = {"% of a week": ["% of a", "week"], "Acme Bare 1 medium": ["Acme Bare", "1 medium"],
          "Acme Top 1 high": ["Acme Top 1", "high"], "Acme Plain 1": ["Acme Plain", "1"]}
# Each role's quality and share of a week: NEW_SEATS's costs at $1.20 a point
NUMBERS = {"orchestrator": ["70.0", "≈0.03%"], "executor": ["100.0", "0.20%"],
           "reviewer": ["95.0", "≈0.25%"]}


def stacked(want):
    """Whether a screen's lines from `quality` to the blank line under them, one space between
    words, are `want`."""
    def test(screen):
        shown = [" ".join(line.split()) for line in lines(screen)]
        try:
            first = shown.index("quality")
            return shown[first:shown.index("", first)] == want
        except ValueError:
            return False
    return test


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsNumbersStack(unittest.TestCase):
    def test_on_22_and_14_cells_each_roles_quality_stands_over_its_cost_inside_the_edge(self):
        home = role_lines.made(self.addCleanup)
        home.write(".agentkit/state/models-unit", "% of a week")
        for width, broken in ((22, {}), (14, BROKEN)):
            with self.subTest(width=width):
                term = Terminal(home, size=(width, 40), env=ENV)
                self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                                server=SERVER)
                term.wait("esc leave")
                term.keys("c")
                term.wait("esc back")
                term.keys("r")
                # `›` on the orchestrator, as the screen opens on it
                term.wait(stacked(["quality", *broken.get("% of a week", ["% of a week"]), *(
                    line for word, model, *_ in role_lines.NEW_SEATS.values()
                    for line in ["› " * (word == "orchestrator") + word,
                                 *broken.get(model, [model]), *NUMBERS[word]])]))


if __name__ == "__main__":
    unittest.main()
