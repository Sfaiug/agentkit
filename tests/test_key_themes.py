"""ak draws every colour as a role of the owner's two themes, white and black, and no other.

The owner (12 Nov 2026): white where the terminal's background is light, black everywhere else,
a seat's bar among them.  `working` and the highlight's `›` are the accent, `needs you` a
warning, `done` a success, `out of usage` an error, `idle` and the key line's keys dim; the
pointer lights a key on the selection, and a seat's bar opens with its state as a chip,
on-accent on the state's role.  The terminal here is tmux, which answers OSC 11 only once a
background is set for its panes (`window-style`), so it stands for both a terminal that never
answers and one that answers.  Black-box: the program AK_BIN names runs in a person's terminal
of 24-bit colour (tests/fixtures/akterm.py) over tests/fixtures/akseat.py's seats, each cell
judged by how it looks (tests/fixtures/aklooks.py), never by the bytes that drew it.  Its
clock injected: `AK_MOTION_CLOCK` names a file of seconds that stands still until the test moves
it, so what moves is told from what rests at the moments the test sets, however late a busy host
draws or captures a frame.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

# role: its colour in the white theme, and in the black
THEMES = {
    "background": ("ffffff", "000000"), "surface": ("f4f6fa", "111519"),
    "selection": ("dcecff", "08305d"), "border": ("b1b8c0", "3a3f46"),
    "text": ("181c22", "e2e8ef"), "muted": ("535962", "acb4bd"), "dim": ("6f757e", "868d97"),
    "accent": ("0067c6", "4da3ff"), "success": ("007935", "33b65f"),
    "warning": ("8e5e00", "d79200"), "error": ("c52a2f", "fe756f"), "info": ("00747d", "00b0bf"),
    "special": ("a23baa", "da7de0"), "on-accent": ("ffffff", "000000")}
WHITE, BLACK = 0, 1
WORDS = ("● working", "! needs you", "✓ done", "○ idle", "○ out of usage")
OPENED = 1000.0     # the moment ak's motion stands at as the screen opens
# a cell rests where it keeps its look at each of these: a breath, which takes two seconds, in
# quarters, long after what moves as the screen opens has moved on, every `●` changing at each
MOMENTS = [OPENED + 10 + quarter / 4 for quarter in range(1, 9)]


def fg(rgb):
    return "38;2;" + ";".join(str(int(rgb[at:at + 2], 16)) for at in (0, 2, 4))


def bg(rgb):
    return "48" + fg(rgb)[2:]


def role(name, theme, ground=fg):
    return ground(THEMES[name][theme])


def colours(shown):
    """The colours of a look, its text's and its background's, in any of SGR's forms."""
    return set(shown) - ATTRIBUTES


def colour(shown):
    """The one colour of a look: none, or a background too, fails the test."""
    [found] = colours(shown)
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Themes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        Seat(home, "beta", screen="claude-question-pane.txt")
        Seat(home, "gamma")
        home.write(".agentkit/state/plan-gamma.md", "- [x] Shipped it\n")
        Seat(home, "delta")
        Seat(home, "omega")
        home.write(".agentkit/state/seat-omega.json", {"usage_wait": {
            "reason": "anthropic out of usage until 2026-10-21 09:00", "until": time.time() + 3600,
            "since": time.time() - 60, "continue": True}})
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(home, "--help").exit_code()
        cls.clock = home.root / "clock"

    def at(self, seconds):
        """ak's motion at `seconds` from now on: its clock's file swapped whole, never read half
        written."""
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def menu(self, background=None):
        """The ak screen on a true-colour terminal of that background, or of none, once it shows
        every seat's word, its motion at OPENED."""
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        self.at(OPENED)
        menu = Terminal(self.home, size=(100, 40),
                        env={"COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock)})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait(lambda text: all(word in text for word in WORDS) and "esc leave" in text, 60)
        return menu

    def screen(self, background=None):
        """The ak screen's looks (`menu`) at the last of MOMENTS, then each cell's look where it
        kept it at all of them, else None, as what breathes or pulses never rests."""
        menu = self.menu(background)
        captures = [looks(menu.screen(colours=True))]
        for moment in MOMENTS:
            self.at(moment)
            deadline = time.monotonic() + 30
            while (shown := looks(menu.screen(colours=True))) == captures[-1]:
                self.assertLess(time.monotonic(), deadline, f"ak drew no frame at {moment}")
                time.sleep(0.05)
            captures.append(shown)
        rest = [[cell if all(len(line) > at and line[at] == cell for line in rows) else None
                 for at, cell in enumerate(rows[0])] for rows in zip(*captures[1:])]
        return captures[-1], rest

    def assert_states(self, screen, theme):
        # `●` breathes, so `working` is the word alone
        self.assertEqual(colour(look(screen, "›")), role("accent", theme))
        for word, name, seat in (("working", "accent", "acme"), ("! needs you", "warning", "beta"),
                                 ("✓ done", "success", "gamma"), ("○ idle", "dim", "delta"),
                                 ("○ out of usage", "error", "omega")):
            with self.subTest(word):
                self.assertEqual(colour(look(screen, word, on=seat)), role(name, theme))
        for key in ("↑↓←→", "esc"):
            self.assertEqual(colour(look(screen, key, on="esc leave")), role("dim", theme))

    def test_on_a_terminal_that_sets_no_background_each_state_is_its_role_of_black(self):
        self.assert_states(self.screen()[0], BLACK)

    def test_on_a_white_background_each_state_is_its_role_of_white(self):
        self.assert_states(self.screen("#ffffff")[0], WHITE)

    def test_at_rest_no_cell_is_drawn_in_a_colour_outside_its_theme(self):
        for background, theme in ((None, BLACK), ("#ffffff", WHITE)):
            with self.subTest(background=background):
                _, rest = self.screen(background)
                drawn = {part for line in rest for cell in line if cell
                         for part in colours(cell[1])}
                self.assertTrue(drawn)
                owned = {ground(rgbs[theme]) for rgbs in THEMES.values() for ground in (fg, bg)}
                self.assertEqual(drawn - owned, set())

    def test_the_pointer_on_a_key_draws_it_on_the_selection(self):
        for background, theme in ((None, BLACK), ("#ffffff", WHITE)):
            with self.subTest(background=background):
                menu = self.menu(background)
                lines = menu.screen().split("\n")
                row = next(n for n, line in enumerate(lines) if "esc leave" in line)
                # the middle of `config`: inside the key, whatever width a glyph before it takes
                at = lines[row].index("c config") + len("c co")
                menu.type(f"\x1b[<35;{at};{row + 1}M")
                lit, deadline = None, time.monotonic() + 30
                while lit != {role("selection", theme, bg)}:
                    self.assertLess(time.monotonic(), deadline, f"`c config` is drawn on {lit}")
                    time.sleep(0.05)
                    line = looks(menu.screen(colours=True))[row]
                    if "c config" in plain(line):
                        at = plain(line).index("c config")
                        # each cell's background, None where it has none
                        lit = {next((part for part in shown if part.startswith("48")), None)
                               for _, shown in line[at:at + len("c config")]}

    def test_a_seats_bar_opens_with_its_state_on_accent_on_its_role(self):
        for seat, word, name in (("acme", "● working", "accent"),
                                 ("beta", "! needs you", "warning")):
            with self.subTest(word):
                term = Terminal(self.home, "orch", seat, size=(100, 30),
                                env={"COLORTERM": "truecolor"})
                self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
                done = self.home.ak("orch", "why", seat)      # a look at the seat dresses its bar
                self.assertEqual(done.code, 0, done.err)
                term.wait(lambda text: word in "\n".join(text.rstrip("\n").split("\n")[-2:]))
                # ak's tmux learns the terminal takes true colour from its answer, which a busy
                # host can pass on after the bar's first draw: the bar is judged as it settles
                wanted = {role("on-accent", BLACK), role(name, BLACK, bg)}
                deadline = time.monotonic() + 30
                while True:
                    shown = colours(look(looks(term.screen(colours=True).rstrip("\n"))[-2:], word))
                    if shown == wanted or time.monotonic() > deadline:
                        break
                    time.sleep(0.2)
                self.assertEqual(shown, wanted)


if __name__ == "__main__":
    unittest.main()
