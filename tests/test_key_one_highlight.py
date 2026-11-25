"""One highlight: what Enter or a click acts on stands on the theme's selection, all of it and
nothing else.

The owner (10 Nov 2026): every screen feels and is operated the same way; each theme (12 Nov)
has a colour for what is lit, `selection`.  A seat's row, the keys' or the pointer's, is on it
from its `›` to the layout's last column, bold behind the `›` as before, and no other row is;
where the terminal draws fewer than 256 colours the row has its `›` alone.  A cell -- a mark on
`c` as wide as its column, set or not, a subscription's meter as wide as its cell, an act on a
subscription's line or a list's answer with a cell before and after it, an act bracketed with
no colour -- is on it over its whole width, the same from the keys and the pointer, and its row
has no band of its own; nothing on `c` or Subscriptions is reversed.  Of a mark on `c` under the
pointer, the owner (10 Nov): "it looks and feels like you can press it, but you cant": every
cell so drawn takes the click, all of it, its padding too, and what no
click acts on -- a model's name on `c`, the arrows' words on the key line -- is not lit, the
pointer there as on blank space; a key of the key line is lit as its text with a cell before and
after.  Black-box: the program `AK_BIN` names runs in a person's terminal that sets no background
(tests/fixtures/akterm.py), over seats (tests/fixtures/akseat.py) and faked harnesses
(tests/fixtures/fakeadapter.py), each cell judged by how it looks once the screen rests
(tests/fixtures/aklooks.py); the pointer's moves and clicks are typed as the SGR reports a
terminal sends.
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
from fixtures.draws import draws

SELECTION, BLACK = "48;2;8;48;93", "48;2;0;0;0"     # the black theme's selection, background
COMES = "48;2;39;100;166"       # ... and where the highlight comes (tests/test_highlight_glows.py)
WIDTH = 100                                         # the terminal's, and so the layout's
MAIN_KEYS = "↑↓←→ move   ⏎ open   n new   c config   esc leave"
MARKS = "●○■□"
ACT, REMOVE = "→ spend a reset", "− remove"         # ChatGPT's acts, a reset in hand


def ground(shown):
    """A look's background, in any of SGR's forms; None where it has none."""
    return next((part for part in shown if part.startswith("48") or part.isdigit()
                 and int(part) in (*range(40, 48), *range(100, 108))), None)


def grounds(shown):
    """Every background a cell of the screen is on, None for the terminal's own."""
    return {ground(look) for line in shown for _, look in line}


def lit_rows(shown, on=SELECTION):
    """{row, from 1: its columns on the selection, or `on`} of the rows that have any."""
    return {row: columns for row, line in enumerate(shown, 1)
            if (columns := [column for column, (_, look) in enumerate(line, 1)
                            if ground(look) == on])}


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
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        # read for both subscriptions, ChatGPT's holding a reset: its line offers two acts
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}], "error": None}
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
                         and any(plain(line).split()[:3] == ["›", "1", "acme"]
                                 for line in shown))

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

    def test_on_c_a_click_on_a_lit_marks_first_or_last_cell_sets_that_mark(self):
        first = self.config()
        (_, fable), (_, astra) = self.row(first, "Fable 5.1"), self.row(first, "6 Astra")
        orch = next(column for column, char in enumerate(plain(first[fable - 1]), 1)
                    if char in MARKS)
        # Astra's orchestrator mark by the first cell lit under the pointer, then Fable's by
        # the last: blanks either side of the mark, set or not, as `c` marks new seats'
        for row, edge in ((astra, 0), (fable, -1)):
            self.term.type(point(orch, row))
            shown = self.calm(lambda shown: orch in lit_rows(shown).get(row, []))
            self.assertEqual(plain(shown[row - 1])[orch - 1], "○")
            column = lit_rows(shown)[row][edge]
            self.assertEqual(plain(shown[row - 1])[column - 1], " ")
            self.term.type(click(column, row))
            self.calm(lambda shown: plain(shown[row - 1])[orch - 1] == "●")

    def test_on_c_a_models_name_and_the_arrows_words_take_no_light_and_no_click(self):
        shown = self.config()
        saved = (self.home.path / ".agentkit" / "config.toml").read_bytes()
        keys = next(row for row, line in enumerate(shown, 1) if "esc back" in plain(line))
        back = self.row(shown, "esc back")
        for name, (col, row) in (("a model's name", self.row(shown, "6 Astra")),
                                 ("the arrows' words", self.row(shown, "↑↓←→ move"))):
            with self.subTest(name):
                self.term.type(point(col + 2, row))
                before = self.calm(lambda shown: not starts(shown, "›"))
                self.assertEqual(lit_rows(before), {})
                # read after the click: the pointer on `esc back`, lit there alone
                self.term.type(click(col + 2, row) + point(*back))
                shown = self.calm(lambda shown: list(lit_rows(shown)) == [keys])
                self.assertEqual((self.home.path / ".agentkit" / "config.toml").read_bytes(),
                                 saved)
                self.term.type(point(col + 2, row))     # back where it clicked: as before it
                after = self.calm(lambda shown: not lit_rows(shown))
                self.assertEqual(after[1:], before[1:])     # under the header's clock
        # `esc back` is lit with a cell before and after it, and a click there goes back
        self.assertEqual(lit_rows(shown)[keys], list(range(back[0] - 1,
                                                           back[0] + len("esc back") + 1)))
        self.term.type(click(*back))
        self.rest(lambda shown: any(MAIN_KEYS in plain(line) for line in shown))

    def test_a_click_on_either_end_of_a_lit_meter_lists_its_acts_as_enter_does(self):
        # ChatGPT's meter, holding a reset, on the ak screen and then on `c`: lit under the
        # pointer over its whole cell, blanks past its last word too, and a click on its first
        # or last lit cell lists its acts, `ACT` among them, as Enter on it does
        self.main(COLORTERM="truecolor")
        for screen, keys in (("the ak screen", MAIN_KEYS), ("c", "esc back")):
            with self.subTest(screen):
                if screen == "c":
                    self.term.keys("c")

                def back(shown):        # the screen, no list over it
                    return (any(keys in plain(line) for line in shown)
                            and not any(ACT in plain(line) for line in shown))
                col, row = self.row(self.rest(back), "ChatGPT")
                for edge in (0, -1):
                    self.term.type(point(col + 1, row))
                    shown = self.rest(lambda shown: col in lit_rows(shown).get(row, []))
                    lit = lit_rows(shown)[row]
                    self.assertEqual(lit, list(range(col, lit[-1] + 1)))
                    self.assertEqual(plain(shown[row - 1])[lit[-1] - 1], " ")
                    self.term.type(click(lit[edge], row))
                    self.rest(lambda shown: any(ACT in plain(line) for line in shown))
                    self.term.keys("Escape")
                    self.rest(back)

    def chatgpt(self):
        """Subscriptions from `c`, the keys on ChatGPT's line's first act, `ACT`."""
        self.config()
        self.term.keys("Down", "Down", "Down")      # past 6 Astra and `Models`
        self.calm(lambda shown: starts(shown, "› Subscriptions"))
        self.term.keys("Enter")
        self.calm(lambda shown: starts(shown, "› Claude"))
        self.term.keys("Down", "Right")
        return self.calm(lambda shown: starts(shown, "› ChatGPT") and lit_rows(shown))

    def test_on_subscriptions_the_keys_act_and_the_pointers_are_drawn_alike(self):
        shown = self.chatgpt()
        col, row = self.row(shown, ACT)
        span = list(range(col - 1, col + len(ACT) + 1))     # with a cell before and after
        self.assertEqual(lit_rows(shown), {row: span})
        keyed = shown[row - 1]
        self.term.keys("Right")                     # onto `− remove`: the act is at rest
        self.calm(lambda shown: lit_rows(shown).get(row, [0])[0] > span[-1])
        self.term.type(point(col + 3, row))
        shown = self.calm(lambda shown: col in lit_rows(shown).get(row, []))
        self.assertEqual(lit_rows(shown), {row: span})
        self.assertEqual(shown[row - 1], keyed)

    def test_an_act_filling_a_narrow_line_is_lit_on_that_line_alone(self):
        self.chatgpt()
        self.term.resize(len(ACT) + 4, 40)          # the act, past the indent, fills the line
        shown = self.calm(lambda shown: len(shown[0]) == len(ACT) + 4
                          and starts(shown, f"    {ACT}"))
        col, row = self.row(shown, ACT)
        # lit from the cell before it to the last column, the act after it on the next row
        self.assertEqual(lit_rows(shown), {row: list(range(col - 1, len(ACT) + 5))})
        self.assertEqual(self.row(shown, REMOVE), (col, row + 1))
        # the pointer where that one is drawn lights it, and the first at rest
        self.term.type(point(col + 3, row + 1))
        shown = self.calm(lambda shown: row + 1 in lit_rows(shown))
        self.assertEqual(lit_rows(shown), {row + 1: list(range(col - 1, col + len(REMOVE) + 1))})
        self.assertEqual((self.row(shown, ACT), self.row(shown, REMOVE)),
                         ((col, row), (col, row + 1)))

    def test_a_bracketed_act_wraps_within_a_narrow_line_with_no_colour(self):
        term = Terminal(self.home, size=(WIDTH, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane,
                        "sleep 86400", server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("› Fable 5.1")
        term.keys("Down", "Down", "Down")
        term.wait("› Subscriptions")
        term.keys("Enter")
        term.wait("› Claude")
        term.keys("Down", "Right")
        term.wait(f"[{ACT}]")
        term.resize(len(ACT) + 4, 40)
        shown = term.wait(lambda screen: "    1 reset in hand" in screen
                          and "\n  esc back" in screen)
        # `[→ spend a reset]` is two cells wider than the line: wrapped at words, not by the
        # terminal, so `− remove` sits on the row recorded for it
        lines = [line.rstrip() for line in shown.splitlines()]
        row = next(number for number, line in enumerate(lines, 1) if line.startswith("    ["))
        self.assertEqual(lines[row - 1:row + 2], ["    [→ spend a", "    reset]", f"    {REMOVE}"])
        term.type(point(8, row + 2))
        term.wait(f"    [{REMOVE}]")

    def test_a_lists_answer_is_lit_over_its_text_and_a_cell_each_side(self):
        # the stop card, asked in acme's popup: each answer a cell, its row no band
        self.term = Terminal(self.home, "attach", "--overlay", size=(WIDTH, 40),
                             env={"AGENTKIT_SESSION": "acme", "COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.rest(lambda shown: any("x stop" in plain(line) for line in shown))
        self.term.keys("x")
        for answer, key in (("✓ Keep", None), ("× Stop", "Down")):
            if key:
                self.term.keys(key)
            shown = self.calm(lambda shown: any(f"› {answer}" in plain(line) for line in shown))
            col, row = self.row(shown, answer)
            self.assertEqual(lit_rows(shown), {row: list(range(col - 1, col + len(answer) + 1))})

    def test_the_row_down_left_fades_into_the_background(self):
        # (the owner, 12 Nov 2026: "glowing effect ... when selection things") in 0.2 s of ak's
        # clock, `AK_MOTION_CLOCK`: a file of seconds that stands still till the test moves it
        clock, new = self.home.root / "clock", self.home.root / "new"
        new.write_text("1000")
        new.replace(clock)
        shown = self.main(COLORTERM="truecolor", AK_MOTION_CLOCK=str(clock))
        acme = self.row(shown, "1  acme")[1]
        band, backs = lit_rows(shown)[acme], []
        for moment in ("1010", "1010.1", "1010.15", "1010.2"):
            new.write_text(moment)
            new.replace(clock)
            if not backs:
                self.term.keys("Down")      # at 1010, as the clock stands: acme still lit
            shown = self.rest(lambda shown: starts(shown, "› 2  beta"))
            backs += [{ground(shown[acme - 1][column - 1][1]) for column in band}]
        self.assertEqual((backs[0], backs[-1]), ({SELECTION}, {BLACK}))
        sums = [sum(map(int, back.split(";")[2:])) for (back,) in backs]
        self.assertEqual(sums, sorted(set(sums), reverse=True))

    def test_the_row_the_pointer_leaves_while_a_number_waits_fades_too(self):
        # ten seats: `1` waits half a second for a second digit, the menu up as ever; the
        # fade's first frame, ak's clock standing, as beta's highlight comes, is read from the
        # program's own bytes (`pipe-pane`), `9` ending the wait on no seat
        for n in range(8):
            Seat(self.home, f"crew-{n}", model="fable")
        clock, raw = self.home.root / "clock", self.home.root / "raw"
        clock.write_text("1000")
        shown = self.main(COLORTERM="truecolor", AK_MOTION_CLOCK=str(clock))
        acme, (number, beta) = self.row(shown, "1  acme")[1], self.row(shown, "2  beta")
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.type("1" + point(number + 3, beta) + "9")
        self.assertNotIn(acme, lit_rows(self.rest(lambda shown: starts(shown, "›  2  beta"))))
        lit = [(lit_rows(shown).keys(), lit_rows(shown, COMES).keys())
               for shown in map(looks, draws(raw.read_text("utf-8")))]
        self.assertTrue(any(acme in fading and beta in coming for fading, coming in lit), lit)

    def tick(self, moment):
        """ak's clock at `moment`: `AK_MOTION_CLOCK`'s file, which it names, standing still
        till the test moves it."""
        clock, new = self.home.root / "clock", self.home.root / "new"
        new.write_text(moment)
        new.replace(clock)
        return str(clock)

    def asked_under(self, name, answer, since):
        """`x` over `name`'s row, lit, as ak's clock stands at `since`: the row where it was
        under the card asked under it, and its band's backgrounds then, a tenth of a second
        on, there still with the pointer moved onto `answer`, and at 0.2 s."""
        shown = self.rest(lambda shown: starts(shown, f"› 1  {name}") and lit_rows(shown))
        row = self.row(shown, f"1  {name}")[1]
        band, backs = lit_rows(shown)[row], []
        self.term.keys("x")
        for after, on in (("", "✓ Keep"), (".1", "✓ Keep"), (".1", answer), (".2", answer)):
            if on == answer and len(backs) == 2:
                self.term.type(point(*self.row(shown, answer)))
            self.tick(f"{since}{after}")
            shown = self.rest(lambda shown: any(f"› {on}" in plain(line) for line in shown))
            self.assertTrue(starts(shown, f"  1  {name}", row))
            backs += [{ground(shown[row - 1][column - 1][1]) for column in band}]
        return backs

    def test_the_row_a_card_is_asked_under_fades_whatever_the_pointer_does(self):
        # (the owner, 20 Nov 2026: "Build the fade") as the row Down left does, under the stop
        # card in acme's popup and under past sessions' own, over a seat the owner stopped
        self.home.write(".agentkit/state/session-crew.json", {
            "orchestrator": "fable", "workers": ["fable"], "cwd": str(self.home.path),
            "created": int(time.time()) - 90000})
        self.home.write(".agentkit/state/seat-crew.json", {
            "stopped_at": time.time() - 9000, "closed_by_owner": True})
        self.term = Terminal(self.home, "attach", "--overlay", size=(WIDTH, 40),
                             env={"AGENTKIT_SESSION": "acme", "COLORTERM": "truecolor",
                                  "AK_MOTION_CLOCK": self.tick("1000")})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.rest(lambda shown: any("x stop" in plain(line) for line in shown))
        self.tick("1010")                           # the popup up, its coming over
        stop = self.asked_under("acme", "× Stop", 1010)
        self.term.keys("Escape", "p")               # kept: past sessions, opening as it stands
        self.tick("1030")
        for backs in (stop, self.asked_under("crew", "× Remove", 1030)):
            self.assertEqual((backs[0], backs[1], backs[3]), ({SELECTION}, backs[2], {BLACK}))
            sums = [sum(map(int, back.split(";")[2:])) for (back,) in backs[:2]]
            self.assertTrue(sums[0] > sums[1] > 0, sums)

    def test_a_meter_under_a_card_is_nothing_the_pointer_lands_on(self):
        # `a` asks before every session takes a new window's marks: the pointer on ChatGPT's
        # meter is off its card's answers, as on a row there, so Enter only lights Apply again
        self.config()
        self.term.keys("a")
        self.term.wait("› ✓ Keep")
        self.term.keys("Down")
        shown = self.rest(lambda shown: starts(shown, "› × Apply"))
        self.term.type(point(*self.row(shown, "ChatGPT")))
        self.rest(lambda shown: starts(shown, "  × Apply"))
        self.term.keys("Enter")
        self.rest(lambda shown: starts(shown, "› × Apply"))

    def test_in_sixteen_colours_a_seat_has_its_mark_alone(self):
        self.assertEqual(grounds(self.main(TERM="xterm-16color")), {None})


if __name__ == "__main__":
    unittest.main()
