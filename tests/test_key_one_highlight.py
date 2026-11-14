"""One highlight: what Enter or a click acts on stands on the theme's selection, all of it and
nothing else, drawn alike by the keys and by the pointer.

The owner (14 Nov 2026): a row acted on whole -- a seat -- is on the selection from its `›` to
the layout's last column; a cell -- a mark on `c` as wide as its column, set or not, an act, a
key of the key line -- over its whole width, an act and a key with a cell before and after; and
every cell so drawn takes the click.  What no click acts on -- a model's name on `c`, the
arrows' words on the key line -- is not lit, and the pointer there is as on blank space.  Nothing
is reversed where colour is drawn.  Black-box: the program `AK_BIN` names runs in a person's
terminal of 24-bit colour that sets no background (tests/fixtures/akterm.py), over seats
(tests/fixtures/akseat.py) and faked harnesses (tests/fixtures/fakeadapter.py), each cell judged
by how it looks once the screen rests (tests/fixtures/aklooks.py); the pointer's moves and clicks
are typed as the SGR reports a terminal sends.  This test fails against `/bin/false`.
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


def lit(line):
    """The columns, from 1, of a line's cells on the selection."""
    return [column for column, (_, shown) in enumerate(line, 1) if ground(shown) == SELECTION]


def lit_rows(shown):
    """{row, from 1: its columns on the selection} of the rows that have any."""
    return {row: columns for row, line in enumerate(shown, 1) if (columns := lit(line))}


def starts(shown, text, row=None):
    """Whether a line of `shown` -- row `row`, from 1, where given -- starts with `text`."""
    return any(plain(line).startswith(text) for line in (shown if row is None else
                                                          shown[row - 1:row]))


def point(col, row):
    return f"\x1b[<35;{col};{row}M"


def click(col, row):
    return f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OneHighlight(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        now = time.time()

        def used(percent):
            return {"meters": [{"name": "weekly", "used": percent, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": {"accounts": {"default": used(16), "two": used(71)}},
            "openai": used(0)}})

        def login(email, ends=None):
            return {"email": email, "ends": ends, "plan": None, "checked_at": now}
        # Claude II's login ends soon, so its line offers `→ log in again` before `− remove`
        self.home.write(".agentkit/state/logins.json", {
            "anthropic": {"default": login("owner@acme.test"),
                          "two": login("two@acme.test", int(now + 2 * 86400))},
            "openai": {"default": login("owner@acme.test")}})
        Seat(self.home, "acme", model="fable")
        Seat(self.home, "beta", model="fable")
        # the terminals' tmux sets no background for its panes (`window-style`) unless told to
        self.term = Terminal(self.home, size=(WIDTH, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)

    def rest(self, ready, bound=30):
        """The screen's looks once it has stood still for a second and `ready(looks)` holds of
        them; no cell of it on a background but the terminal's, black or the selection, none
        reversed.  Each line to the last column: tmux drops a line's trailing blanks, a band's
        too, unless asked to keep them (`-N`)."""
        deadline, last, since = time.monotonic() + bound, None, None
        while True:
            done = self.home.tmux("capture-pane", "-p", "-e", "-N", "-t", self.term.pane,
                                  server=SERVER)
            self.assertEqual(done.code, 0, done.err)
            if done.out != last:
                last, since = done.out, time.monotonic()
            elif time.monotonic() - since >= 1 and ready(shown := looks(last)):
                break
            self.assertLess(time.monotonic(), deadline, SGR.sub("", last))
            time.sleep(0.1)
        for row, line in enumerate(shown, 1):
            for column, (char, look) in enumerate(line, 1):
                self.assertIn(ground(look), (None, BLACK, SELECTION), (row, column, char))
                self.assertNotIn("7", look, (row, column, char))
        return shown

    def where(self, shown, text, nth=0):
        """(column, row) of the first cell of the `nth` place `text` shows, counted from 1."""
        found = [(plain(line).index(text) + 1, row) for row, line in enumerate(shown, 1)
                 if text in plain(line)]
        return found[nth]

    def main(self):
        return self.rest(lambda shown: any(MAIN_KEYS in plain(line) for line in shown)
                         and starts(shown, "› 1  acme"))

    def config(self):
        self.term.keys("c")
        return self.rest(lambda shown: starts(shown, "› Fable 5.1")
                         and any("esc back" in plain(line) for line in shown))

    def marks(self, shown, row):
        """The columns, from 1, of the marks on `row`."""
        return [column for column, char in enumerate(plain(shown[row - 1]), 1) if char in MARKS]

    def test_a_seat_is_lit_from_its_mark_to_the_layouts_last_column_by_keys_and_pointer(self):
        shown = self.main()
        acme, beta = (self.where(shown, name)[1] for name in ("1  acme", "2  beta"))
        self.assertEqual(lit_rows(shown), {acme: list(range(1, WIDTH + 1))})
        self.term.type(point(WIDTH - 1, beta))      # far past its name, inside the layout
        shown = self.rest(lambda shown: starts(shown, "› 2  beta", beta))
        self.assertTrue(plain(shown[acme - 1]).startswith("  1  acme"))
        rows = lit_rows(shown)
        self.assertNotIn(acme, rows)
        self.assertEqual(min(rows), beta)           # beta's row, and any line it opens under it
        self.assertEqual(sorted(rows), list(range(beta, beta + len(rows))))
        self.assertEqual(set(map(tuple, rows.values())), {tuple(range(1, WIDTH + 1))})

    def test_on_c_a_mark_is_lit_over_its_column_alike_by_keys_and_pointer(self):
        self.main()
        shown = self.config()
        fable, astra = (self.where(shown, name)[1] for name in ("Fable 5.1", "6 Astra"))
        orch = self.marks(shown, fable)[0]
        self.assertEqual(plain(shown[fable - 1])[orch - 1], "●")       # the orchestrator's
        # the keys' cell: that mark, over its column, its row's `›` and no band
        rows = lit_rows(shown)
        self.assertEqual(list(rows), [fable])
        keyed = rows[fable]
        self.assertIn(orch, keyed)
        self.assertEqual(keyed, list(range(keyed[0], keyed[-1] + 1)))
        self.assertNotIn(1, keyed)
        # one not set is as wide
        self.term.keys("Down")
        shown = self.rest(lambda shown: starts(shown, "› 6 Astra", astra))
        self.assertEqual(plain(shown[astra - 1])[orch - 1], "○")
        self.assertEqual(lit_rows(shown), {astra: keyed})
        # the pointer on Fable's next mark lights it the same, and Astra's is at rest
        builds = self.marks(shown, fable)[1]
        self.term.type(point(builds, fable))
        shown = self.rest(lambda shown: starts(shown, "› Fable 5.1", fable))
        rows = lit_rows(shown)
        self.assertEqual(list(rows), [fable])
        self.assertEqual(len(rows[fable]), len(keyed))
        self.assertIn(builds, rows[fable])
        self.assertFalse(plain(shown[astra - 1]).startswith("›"))
        # a click on the first cell lit sets Astra's orchestrator mark, and on the last Fable's
        for row, edge in ((astra, 0), (fable, -1)):
            self.term.type(point(orch, row))
            shown = self.rest(lambda shown: orch in lit(shown[row - 1]))
            self.assertEqual(plain(shown[row - 1])[orch - 1], "○")
            cells = lit_rows(shown)[row]
            self.assertEqual(len(cells), len(keyed))
            self.term.type(click(cells[edge], row))
            self.rest(lambda shown: plain(shown[row - 1])[orch - 1] == "●")

    def test_on_c_a_models_name_and_the_arrows_words_take_no_light_and_no_click(self):
        self.main()
        shown = self.config()
        saved = (self.home.path / ".agentkit" / "config.toml").read_bytes()
        keys = next(row for row, line in enumerate(shown, 1) if "esc back" in plain(line))
        back = self.where(shown, "esc back")
        for name, (col, row) in (("a model's name", self.where(shown, "6 Astra")),
                                 ("the arrows' words", self.where(shown, "↑↓←→ move"))):
            with self.subTest(name):
                self.term.type(point(col + 2, row))
                shown = self.rest(lambda shown: not starts(shown, "›"))
                self.assertEqual(lit_rows(shown), {})
                self.term.type(click(col + 2, row) + point(*back))     # read after the click
                shown = self.rest(lambda shown: list(lit_rows(shown)) == [keys])
                self.assertFalse(starts(shown, "›"))
                self.assertEqual((self.home.path / ".agentkit" / "config.toml").read_bytes(),
                                 saved)
                self.assertTrue(any(plain(line).startswith("agentkit · config")
                                    for line in shown))
        # `esc back` is lit with a cell before and after it, and a click there goes back
        self.assertEqual(lit_rows(shown)[keys], list(range(back[0] - 1, back[0] + len("esc back")
                                                           + 1)))
        self.term.type(click(*back))
        self.main()

    def test_on_subscriptions_the_keys_act_and_the_pointers_are_drawn_alike(self):
        self.main()
        self.config()
        self.term.keys("Down", "Down", "Down")          # past 6 Astra and `Models`
        self.rest(lambda shown: starts(shown, "› Subscriptions"))
        self.term.keys("Enter")
        self.rest(lambda shown: starts(shown, "› Claude I "))
        self.term.keys("Down")
        act = "→ log in again"
        shown = self.rest(lambda shown: starts(shown, "› Claude II")
                          and any(act in plain(line) for line in shown))
        col, row = self.where(shown, act)
        span = list(range(col - 1, col + len(act) + 1))
        self.assertEqual(lit_rows(shown), {row: span})
        keyed = shown[row - 1][span[0] - 1:span[-1]]
        self.term.keys("Right")                         # onto `− remove`: the act is at rest
        shown = self.rest(lambda shown: lit_rows(shown).get(row, [0])[0] > span[-1])
        self.term.type(point(col + 3, row))
        shown = self.rest(lambda shown: col in lit_rows(shown).get(row, []))
        self.assertEqual(lit_rows(shown), {row: span})
        self.assertEqual(shown[row - 1][span[0] - 1:span[-1]], keyed)


if __name__ == "__main__":
    unittest.main()
