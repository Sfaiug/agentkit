"""On a short terminal `r recommended` on `c` keeps what each role uses and fits its bars to the
room: on 40×24, for each role, the role lines, every bar's cost and the key line; on 80×24,
every bar's cost, quality, name and effort, the shaded ones' why and the `━`, the bars shorter
than on 40 rows; on 100×24 under a board's read error, the same.

Black-box: `AK_BIN` in a terminal (tests/fixtures/akterm.py), a fake harness and the boards
held as tests/test_key_models_bars.py holds them, on tests/test_key_role_choices.py's writing;
judged by the screen.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, KEYS, lines
from test_key_models_bars import BARS, ROWS, USES, bars, drawn, held, want
from test_key_models_role_lines import said

# What each role uses on 40 cells, after the column heads, one space between words: its quality
# and cost on its word's line, its model under it
ROLE_LINES = ("quality a task {}orchestrator 96.0 ≈$4.00 Acme Step 1 high {}executor 100.0 ≈$8.00 "
              "Acme Top 1 high {}reviewer 92.0 ≈$2.00 Acme Base 1 high")
ERROR = "HTTP Error 503: Service Unavailable"
NOTE = "  the boards were not read: arena.ai " + ERROR


def keyed(screen):
    """Whether the key line ends the screen, however it folds."""
    return " ".join(screen.split()).endswith(" ".join(KEYS.split()))


def costs(screen, word):
    """The costs on `word`'s bars, left to right, and the role lines, `▸` at `word`; None before
    they are drawn."""
    try:
        return ([bar["cost"] for bar in bars(screen, word)], " ".join(said(screen)))
    except (StopIteration, ValueError, IndexError):
        return None


def labelled(screen, word):
    """Each of `word`'s bars' (name, quality, cost, why, effort), left to right, and the names
    marked `━` (test_key_models_bars.drawn), whether or not a bar stands tall enough to show
    its shade; None before they are drawn."""
    found = drawn(screen, word)
    return found and (found[0], found[3])


def labels(word):
    """`labelled` as test_key_models_bars.want has the bars."""
    found = want(word)
    return found[0], found[3]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsBarsFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        held(cls.home, ROWS)

    def models(self, size, home=None):
        """`r` on `c` in a window of `size` of its own, once its first role's heading is drawn."""
        home = home or self.home
        term = Terminal(home, size=size, env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("\n  orchestrator · ")
        return term

    def roles(self, term, test):
        """Each role's screen in turn, ↓ moving to the next, once `test(screen, word)` holds."""
        for n, word in enumerate(USES):
            if n:
                term.keys("Down")
            yield term.wait(lambda screen: test(screen, word) and keyed(screen))

    def test_on_40_by_24_each_role_keeps_its_lines_every_bars_cost_and_the_key_line(self):
        want_costs = lambda word: ([cost for _, _, cost, _ in BARS], ROLE_LINES.format(
            *("▸ " if role == word else "" for role in USES)))
        list(self.roles(self.models((40, 24)),
                        lambda screen, word: costs(screen, word) == want_costs(word)))

    def test_on_80_by_24_every_bar_keeps_its_labels_why_and_mark_shorter_than_on_40_rows(self):
        tallest = lambda screen: max(bar["eighths"] for bar in bars(screen, "orchestrator"))
        whole = self.models((80, 40)).wait(
            lambda screen: drawn(screen, "orchestrator") == want("orchestrator"))
        shown = list(self.roles(self.models((80, 24)),
                                lambda screen, word: labelled(screen, word) == labels(word)))
        self.assertLess(tallest(shown[0]), tallest(whole))

    def test_on_100_by_24_a_boards_read_error_leaves_every_bar_its_labels_why_and_mark(self):
        home = Home()                 # its close runs after its terminal's cleanup, added later
        self.addCleanup(home.close)
        held(home, ROWS)
        boards = home.path / ".agentkit/state/boards.json"
        stored = json.loads(boards.read_text())
        stored["arena.ai"]["error"] = ERROR
        boards.write_text(json.dumps(stored))
        self.models((100, 24), home).wait(
            lambda screen: NOTE in lines(screen) and keyed(screen)
            and labelled(screen, "orchestrator") == labels("orchestrator"))


if __name__ == "__main__":
    unittest.main()
