"""On `config · your runs` one model's row is highlighted, every line of it where the tables
fold: the first orchestrator's as the page opens, ↑/↓ moving it through the three tables' rows
in their order, the key line naming `↑↓ move`.  On a page too short for the tables the
highlighted row stays on it, the first row's page showing the team line and the last's the
note's last line; on one too short for those too, ↓ on the last row and ↑ on the first turn the
page a line a press, as far as its last and its first line, until the highlight moves, and a
page with no line is not turned.  Black-box: `AK_BIN` in a terminal in every colour over
tests/test_key_models_own_tables.py's history, with a dead proxy, the highlight read as the
lines on the theme's selection; fails against /bin/false."""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.akboards import ENV
from fixtures.akterm import SERVER, Terminal
from test_key_a_screen_is_painted import BLACK
from test_key_models_own_tables import FOLDED, TEAMS, home_of
from test_key_your_runs_screen import AT_100, KEYS, body_lines, last_line

SELECTION = tuple(bytes.fromhex(BLACK[2]))      # the highlight at rest, (r, g, b)
COLOURED = {**{name: value for name, value in ENV.items() if name != "NO_COLOR"},
            "COLORTERM": "truecolor"}


def read(screen):
    """A screen captured with its colours: its lines plain, and those with a cell on the
    selection, the background each code leaves carried from cell to cell and line to line."""
    shown, lit, back = [], [], None
    for line in screen.split("\n"):
        on = False
        for part in re.finditer(r"\x1b\[([\d;]*)m|([^\x1b])", line):
            if part[1] is None:
                on = on or back == SELECTION
                continue
            codes = [int(code or 0) for code in part[1].split(";")]
            while codes:
                code = codes.pop(0)
                if code in (0, 49):
                    back = None
                elif code in (38, 48):      # a colour, its numbers after it
                    size = 4 if codes[:1] == [2] else 2
                    back, codes = (tuple(codes[1:size]) if code == 48 else back), codes[size:]
        shown.append(re.sub(r"\x1b\[[\d;]*m", "", line).rstrip())
        lit += [shown[-1]] * on
    return shown, lit


def rested(term, rows, body, *keys):
    """`keys` pressed, `term`'s lines plain once the highlight rests on `rows` over `body`, the
    lines between the rule and the key line."""
    if keys:
        term.keys(*keys)
    reads = []      # what is asserted of the screen is what the wait read
    term.wait(lambda _: reads.append(read(term.screen(colours=True)))
              or (reads[-1][1], body_lines(reads[-1][0])) == (rows, body))
    return reads[-1][0]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class YourRunsHighlight(unittest.TestCase):
    def open(self, size):
        """`r your runs` on `c`, drawn in every colour on a terminal of `size`."""
        home = home_of(TEAMS)
        self.addCleanup(home.close)
        self.term = Terminal(home, size=size, env=COLOURED)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait("r your runs")
        self.term.keys("r")

    def page(self, rows, body, *keys):
        return rested(self.term, rows, body, *keys)

    def test_it_opens_on_the_first_orchestrator_and_down_moves_to_the_next(self):
        self.open((100, 30))
        self.assertEqual(last_line(self.page(AT_100[3:4], AT_100)), KEYS)
        self.page(AT_100[4:5], AT_100, "Down")

    def test_on_a_short_page_the_last_row_shows_the_note_and_the_first_the_team(self):
        # 12 of the 18 lines on 18 rows, 6 on 12, 2 on 8: the first row is line 3, the last 12
        self.open((100, 18))
        rows = [line for line in AT_100 if line.startswith(("●", "○", "■", "□"))]
        self.page(rows[:1], AT_100[:12])
        self.page(rows[-1:], AT_100[-12:], *["Down"] * (len(rows) - 1))
        self.term.resize(100, 12)
        self.page(rows[-1:], AT_100[-6:])
        self.page(rows[:1], AT_100[:6], *["Up"] * (len(rows) - 1))
        for height, body in ((8, AT_100[2:4]), (12, AT_100[:6])):
            self.term.resize(100, height)
            self.page(rows[:1], body)

    def test_a_step_past_the_last_or_the_first_row_turns_the_page(self):
        # 5 lines on 11 rows: under the last row a blank line and three of the note's four
        self.open((100, 11))
        rows = [line for line in AT_100 if line.startswith(("●", "○", "■", "□"))]
        self.page(rows[-1:], AT_100[-6:-1], *["Down"] * (len(rows) - 1))
        # no further than the page's last line, and ↑ is the row above, the page back on it
        self.page([], AT_100[-5:], "Down", "Down")
        self.page(rows[-2:-1], AT_100[-7:-2], "Up")
        # 2 lines on 8 rows: over the first row its table's heading, the team line two lines up
        self.term.resize(100, 8)
        self.page(rows[:1], AT_100[2:4], *["Up"] * (len(rows) - 2))
        self.page([], AT_100[1:3], "Up")
        self.page([], AT_100[:2], "Up", "Up")
        self.page(rows[1:2], AT_100[3:5], "Down")
        # no line on 6 rows: ↓ on the last row there, `p` read after it, turns nothing for 8
        self.term.resize(100, 6)
        self.page([], [])
        self.term.keys(*["Down"] * (len(rows) - 1), "p")
        self.term.wait("a add a company")
        self.term.keys("Escape")
        self.term.resize(100, 8)
        self.page(rows[-1:], AT_100[12:14])

    def test_on_40_cells_every_line_of_the_highlighted_row_is_lit(self):
        self.open((40, 50))
        self.page(FOLDED[4:7], FOLDED)
        self.page(FOLDED[12:16], FOLDED, "Down", "Down")      # past nova unrecorded, to Bolt 3 max


if __name__ == "__main__":
    unittest.main()
