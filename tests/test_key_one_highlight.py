"""One highlight: a row Enter or a click acts on as a whole stands on the theme's selection.

The owner (10 Nov 2026): every screen feels and is operated the same way; each theme (12 Nov)
has a colour for what is lit, `selection`.  A seat's row, the keys' or the pointer's, is on it
from its `›` to the layout's last column, bold behind the `›` as before, and no other row is;
where the terminal draws fewer than 256 colours the row has its `›` alone.  Black-box: the
program `AK_BIN` names runs in a person's terminal that sets no background
(tests/fixtures/akterm.py), over seats (tests/fixtures/akseat.py) and faked harnesses
(tests/fixtures/fakeadapter.py), each cell judged by how it looks once the screen rests
(tests/fixtures/aklooks.py); the pointer's moves are typed as the SGR reports a terminal sends.
This test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import SGR, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SELECTION, BLACK = "48;2;8;48;93", "48;2;0;0;0"     # the black theme's selection, background
WIDTH = 100                                         # the terminal's, and so the layout's
MAIN_KEYS = "↑↓←→ move   ⏎ open   n new   c config   esc leave"


def ground(shown):
    """A look's background, in any of SGR's forms; None where it has none."""
    return next((part for part in shown if part.startswith("48") or part.isdigit()
                 and int(part) in (*range(40, 48), *range(100, 108))), None)


def grounds(shown):
    """Every background a cell of the screen is on, None for the terminal's own."""
    return {ground(look) for line in shown for _, look in line}


def lit_rows(shown):
    """{row, from 1: its columns on the selection} of the rows that have any."""
    return {row: columns for row, line in enumerate(shown, 1)
            if (columns := [column for column, (_, look) in enumerate(line, 1)
                            if ground(look) == SELECTION])}


def starts(shown, text, row=None):
    """Whether a line of `shown` -- row `row`, from 1, where given -- starts with `text`."""
    return any(plain(line).startswith(text) for line in (shown if row is None else
                                                          shown[row - 1:row]))


def point(col, row):
    return f"\x1b[<35;{col};{row}M"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OneHighlight(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, {"fable": "claude"})
        Seat(self.home, "acme", model="fable")
        Seat(self.home, "beta", model="fable")

    def main(self, **env):
        """The ak screen in a terminal of `env`, and its looks once it rests, the keys on acme;
        the terminals' tmux sets no background for its panes (`window-style`) unless told to."""
        self.term = Terminal(self.home, size=(WIDTH, 40), env=env)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        return self.rest(lambda shown: any(MAIN_KEYS in plain(line) for line in shown)
                         and starts(shown, "› 1  acme"))

    def rest(self, ready, bound=30):
        """The screen's looks once it has stood still for a second and `ready(looks)` holds of
        them.  Each line to the last column: tmux drops a line's trailing blanks, a band's too,
        unless asked to keep them (`-N`)."""
        deadline, last, since = time.monotonic() + bound, None, None
        while True:
            done = self.home.tmux("capture-pane", "-p", "-e", "-N", "-t", self.term.pane,
                                  server=SERVER)
            self.assertEqual(done.code, 0, done.err)
            if done.out != last:
                last, since = done.out, time.monotonic()
            elif time.monotonic() - since >= 1 and ready(shown := looks(last)):
                return shown
            self.assertLess(time.monotonic(), deadline, SGR.sub("", last))
            time.sleep(0.1)

    def row(self, shown, text):
        """(column, row) of the first cell of `text` where the screen shows it, from 1."""
        return next((plain(line).index(text) + 1, row) for row, line in enumerate(shown, 1)
                    if text in plain(line))

    def test_a_seat_is_on_the_selection_from_its_mark_to_the_layouts_last_column(self):
        shown = self.main(COLORTERM="truecolor")
        (_, acme), (number, beta) = self.row(shown, "1  acme"), self.row(shown, "2  beta")
        self.assertEqual(lit_rows(shown), {acme: list(range(1, WIDTH + 1))})
        self.assertLessEqual(grounds(shown), {None, BLACK, SELECTION})
        self.term.type(point(number + 3, beta))     # on its name
        shown = self.rest(lambda shown: starts(shown, "› 2  beta", beta))
        self.assertTrue(plain(shown[acme - 1]).startswith("  1  acme"))
        rows = lit_rows(shown)
        self.assertEqual(min(rows), beta)           # beta's row, and any line it opens under it
        self.assertEqual(sorted(rows), list(range(beta, beta + len(rows))))
        self.assertEqual(set(map(tuple, rows.values())), {tuple(range(1, WIDTH + 1))})
        self.assertLessEqual(grounds(shown), {None, BLACK, SELECTION})

    def test_in_sixteen_colours_a_seat_has_its_mark_alone(self):
        self.assertEqual(grounds(self.main(TERM="xterm-16color")), {None})


if __name__ == "__main__":
    unittest.main()
