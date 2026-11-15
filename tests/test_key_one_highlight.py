"""One highlight: what Enter or a click acts on stands on the theme's selection.

The owner (10 Nov 2026): every screen feels and is operated the same way; each theme (12 Nov)
has a colour for what is lit, `selection`.  A seat's row, the keys' or the pointer's, is on it
from its `›` to the layout's last column, bold behind the `›` as before, and no other row is;
where the terminal draws fewer than 256 colours the row has its `›` alone.  A cell -- a mark on
`c` as wide as its column, set or not, an act on a subscription's line with a cell before and
after it -- is on it over its whole width, the same from the keys and the pointer, and its row
has no band of its own; nothing on `c` or Subscriptions is reversed.  Black-box: the
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
MARKS = "●○■□"


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
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        # read for both subscriptions, ChatGPT's holding a reset: its line offers two acts
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": week, "openai": {**week, "resets": 1}}})
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

    def calm(self, ready):
        """`rest`'s looks, every cell of them on the theme's background or the selection, none
        reversed."""
        shown = self.rest(ready)
        self.assertLessEqual(grounds(shown), {BLACK, SELECTION})
        self.assertEqual([look for line in shown for _, look in line if "7" in look], [])
        return shown

    def config(self):
        """`c` over acme, from the ak screen, the keys on Fable's first mark."""
        self.main(COLORTERM="truecolor")
        self.term.keys("c")
        return self.calm(lambda shown: starts(shown, "› Fable 5.1")
                         and any("esc back" in plain(line) for line in shown))

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

    def test_on_c_a_mark_is_lit_over_its_column_alike_by_keys_and_pointer(self):
        first = self.config()
        (_, fable), (_, astra) = self.row(first, "Fable 5.1"), self.row(first, "6 Astra")
        orch = next(column for column, char in enumerate(plain(first[fable - 1]), 1)
                    if char in MARKS)
        self.assertEqual((plain(first[fable - 1])[orch - 1], plain(first[astra - 1])[orch - 1]),
                         ("●", "○"))                 # the orchestrator's mark, and one not set
        # the keys' mark, set, over its column, and no other cell of its row: no band
        keyed = lit_rows(first)
        self.assertEqual(list(keyed), [fable])
        self.assertIn(orch, keyed[fable])
        self.assertEqual(keyed[fable], list(range(keyed[fable][0], keyed[fable][-1] + 1)))
        self.assertGreater(len(keyed[fable]), len(" ● "))      # its column, not the mark
        # one not set in its column is lit over as many cells
        self.term.keys("Down")
        shown = self.calm(lambda shown: starts(shown, "› 6 Astra", astra))
        self.assertEqual(lit_rows(shown), {astra: keyed[fable]})
        # the pointer on Fable's mark draws it as the keys did, and Astra's as at rest
        self.term.type(point(orch, fable))
        shown = self.calm(lambda shown: starts(shown, "› Fable 5.1", fable))
        self.assertEqual(lit_rows(shown), keyed)
        self.assertEqual((shown[fable - 1], shown[astra - 1]), (first[fable - 1], first[astra - 1]))

    def test_on_subscriptions_the_keys_act_and_the_pointers_are_drawn_alike(self):
        self.config()
        self.term.keys("Down", "Down", "Down")      # past 6 Astra and `Models`
        self.calm(lambda shown: starts(shown, "› Subscriptions"))
        self.term.keys("Enter")
        self.calm(lambda shown: starts(shown, "› Claude"))
        self.term.keys("Down", "Right")             # ChatGPT's line, its first act
        act = "→ spend a reset"
        shown = self.calm(lambda shown: starts(shown, "› ChatGPT") and lit_rows(shown))
        col, row = self.row(shown, act)
        span = list(range(col - 1, col + len(act) + 1))     # with a cell before and after
        self.assertEqual(lit_rows(shown), {row: span})
        keyed = shown[row - 1]
        self.term.keys("Right")                     # onto `− remove`: the act is at rest
        self.calm(lambda shown: lit_rows(shown).get(row, [0])[0] > span[-1])
        self.term.type(point(col + 3, row))
        shown = self.calm(lambda shown: col in lit_rows(shown).get(row, []))
        self.assertEqual(lit_rows(shown), {row: span})
        self.assertEqual(shown[row - 1], keyed)

    def test_in_sixteen_colours_a_seat_has_its_mark_alone(self):
        self.assertEqual(grounds(self.main(TERM="xterm-16color")), {None})


if __name__ == "__main__":
    unittest.main()
