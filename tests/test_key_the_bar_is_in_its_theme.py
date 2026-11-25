"""What tmux draws around a seat is in the theme: its bar, the popup's border, tmux's selection.

The owner (12 Nov 2026): "look at every place where things are visual to the end user inside of
ak, and see through to apply the following two themes."  A seat's bar draws its model and its
key's word muted, its key dim, on the terminal's own background
(tests/test_key_a_seats_bar_sets_no_background.py).  In the seat, tmux's own selection while
scrolling back is the text on the selection; Ctrl-b m's popup is bordered in the border colour,
the seat dim under it till it closes.  Each follows the theme a menu kept last: the bar and the
selection by the bar's next draw, which writes them together, the popup from the next one
opened, whichever ak kept the theme.  A session on the same server that ak did not start keeps
the styles it had: those it holds itself, and the bar's, which it takes from the server.  What
tmux marks it takes from the server in the theme (tests/test_key_what_tmux_marks_is_in_the_look.py).

Black-box: the program AK_BIN names, in a person's terminal of 24-bit colour whose background
a test sets (tests/fixtures/akterm.py), attached by `ak orch acme` to a working seat
(tests/fixtures/akseat.py), each cell judged by how it looks (tests/fixtures/aklooks.py); a seat
ak opens, a fake `claude` in it, gives the server ak's Ctrl-b m.  The tests run in their order.
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

SIZE = (100, 30)
# role: its colour in the black theme, and in the white
BLACK = {"text": "e2e8ef", "muted": "acb4bd", "dim": "868d97", "selection": "08305d",
         "border": "3a3f46"}
WHITE = {"text": "181c22", "muted": "535962", "dim": "6f757e", "selection": "dcecff",
         "border": "b1b8c0"}
CHIP, MODEL, KEY, WORD = "● working", "Opus 5.5 xhigh", "Ctrl-b m", "menu"
STYLES = ("status-style", "message-style", "message-command-style", "mode-style")


def fg(rgb):
    return "38;2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def style(value):
    """A tmux style as the set of what it says, in any order or case."""
    return set(value.strip().lower().split(","))


def others(home):
    """The styles the session ak did not start draws in, its own or the server's."""
    said = home.tmux("display-message", "-p", "-t", "=other:",
                     "\t".join(f"#{{{name}}}" for name in STYLES))
    assert said.code == 0, said.err
    return said.out


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheBarIsInItsTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        done = home.tmux("new-session", "-d", "-s", "other", "sleep 86400")   # not ak's
        assert done.code == 0, done.err
        done = home.tmux("set-option", "-w", "-t", "=other:", "mode-style", "bg=blue,fg=white")
        assert done.code == 0, done.err     # its owner's own, by hand
        cls.others = others(home)
        home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
        done = home.ak("orch", "beta", "--model", "opus", "--workers", "opus", tty=True)
        assert done.code == 0, done.err
        cls.term = Terminal(home, "orch", "acme", size=SIZE, env={"COLORTERM": "truecolor"})
        cls.addClassCleanup(home.tmux, "kill-session", "-t", cls.term.pane, server=SERVER)

    def drawn(self, theme):
        """The bar's two lines once a look at the seat has drawn it in `theme`."""
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        deadline = time.monotonic() + 30
        while (wrong := self.off(bar := self.bar(), theme)) and time.monotonic() < deadline:
            time.sleep(0.2)     # tmux learns the terminal takes true colour as it goes
        self.assertIsNone(wrong, "\n".join(plain(line) for line in bar))
        return bar

    def bar(self):
        return looks(self.term.screen(colours=True).rstrip("\n"))[-2:]

    def off(self, bar, theme):
        """What of the bar is not in `theme`, else None: each part in its role."""
        if len(bar) < 2 or CHIP not in plain(bar[0]) or KEY not in plain(bar[1]):
            return "no bar of a working seat"
        for text, role, line in ((MODEL, "muted", 0), (KEY, "dim", 1), (WORD, "muted", 1)):
            shown = look([bar[line]], text) - ATTRIBUTES
            if fg(theme[role]) not in shown:
                return f"{text!r} is not in the {role}: {shown}"
        return None

    def popup(self, theme):
        """Ctrl-b m's popup, bordered in `theme`'s border, then let go."""
        self.term.keys("C-b", "m")
        self.term.wait("esc leave", 60)
        rows = looks(self.term.screen(colours=True))
        self.assertIn(fg(theme["border"]), look(rows, "╭"))
        self.assertEqual(self.under(f"fg=#{theme['dim']}"), [f"fg=#{theme['dim']}"] * 2)
        self.term.keys("Escape")
        self.term.wait(lambda screen: "esc leave" not in screen, 30)
        self.assertEqual(self.under(""), ["", ""])     # as it was: none of its own

    def under(self, want):
        """The seat pane's own styles, once both are `want` or ten seconds have passed."""
        deadline = time.monotonic() + 10
        while (held := [self.home.tmux("show-options", "-pqv", "-t", "=acme:", name).out.strip()
                        for name in ("window-style", "window-active-style")]) != [want] * 2:
            if time.monotonic() > deadline:
                break
            time.sleep(0.1)
        return held

    def selection(self, theme):
        """tmux's own selection and position while scrolling back in the seat, its window's, are
        the text on `theme`'s selection."""
        held = self.home.tmux("show-options", "-wv", "-t", "=acme:", "mode-style")
        self.assertEqual(held.code, 0, held.err)
        self.assertEqual(style(held.out), {f"fg=#{theme['text']}", f"bg=#{theme['selection']}"})

    def kept(self, background):
        """A menu run on a terminal of that background, which answers what it is."""
        done = self.home.tmux("set-option", "-g", "window-style", f"bg={background}",
                              server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        menu = Terminal(self.home, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait("esc leave", 60)

    def test_a_each_part_of_the_bar_is_in_its_role(self):
        self.drawn(BLACK)

    def test_b_tmux_s_selection_in_the_seat_is_the_theme_s(self):
        self.drawn(BLACK)
        self.selection(BLACK)

    def test_c_the_popup_is_bordered_in_the_border_colour(self):
        self.popup(BLACK)

    def test_d_a_light_background_kept_is_the_next_bar_s_and_popup_s(self):
        self.kept("#ffffff")
        # keeping writes no seat: tmux's own styles change in the bar's one write, its own the
        # terminal's in either theme
        said = self.home.tmux("display-message", "-p", "-t", "=acme:",
                              "\t".join(f"#{{{name}}}" for name in STYLES))
        self.assertIn([style(value) for value in said.out.strip().split("\t")],
                      [[{"default"}] * 3 + [style(f"fg=#{theme['text']},bg=#{theme['selection']}")]
                       for theme in (BLACK, WHITE)])
        self.drawn(WHITE)
        self.selection(WHITE)
        self.popup(WHITE)

    def test_e_the_popup_is_in_the_theme_kept_as_the_key_is_pressed(self):
        self.kept("#000000")
        self.popup(BLACK)

    def test_f_a_session_ak_did_not_start_keeps_its_styles(self):
        self.assertEqual(others(self.home), self.others)


if __name__ == "__main__":
    unittest.main()
