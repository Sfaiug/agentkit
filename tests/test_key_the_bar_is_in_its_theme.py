"""What tmux draws around a seat is in the theme: its bar, the popup's border, tmux's own styles.

The owner (12 Nov 2026): "look at every place where things are visual to the end user inside of
ak, and see through to apply the following two themes."  A seat's bar stands on the theme's
surface from its first cell to its last: its name in the text, its model and its key's word
muted, its key dim, its state's chip on-accent on the state's colour.  In the seat, tmux's own
selection while scrolling back is the text on the selection, its message line the text on the
surface; Ctrl-b m's popup is bordered in the border colour, the seat dim under it till it
closes.  Each follows the theme chosen on `c`: the bar and tmux's own styles by the bar's next
draw, which writes them together, the popup from the next one opened, whichever ak chose the
theme.  A session on the same server that ak did not start keeps the styles it had.

Black-box: the program AK_BIN names, in a person's terminal of 24-bit colour that sets no
background (tests/fixtures/akterm.py), attached by `ak orch acme` to a working seat
(tests/fixtures/akseat.py), each cell judged by how it looks (tests/fixtures/aklooks.py); a seat
ak opens, a fake `claude` in it, gives the server ak's Ctrl-b m.  The tests run in their order.
"""

import sys
from pathlib import Path
import re
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SIZE = (100, 30)
# role: its colour in the black theme, and in the white
BLACK = {"surface": "111519", "text": "e2e8ef", "muted": "acb4bd", "dim": "868d97",
         "selection": "08305d", "border": "3a3f46", "accent": "4da3ff", "on-accent": "000000"}
WHITE = {"surface": "f4f6fa", "text": "181c22", "muted": "535962", "dim": "6f757e",
         "selection": "dcecff", "border": "b1b8c0", "accent": "0067c6", "on-accent": "ffffff"}
CHIP, MODEL, KEY, WORD = "● working", "Opus 5.5 xhigh", "Ctrl-b m", "menu"
STYLES = ("status-style", "message-style", "mode-style")


def fg(rgb):
    return "38;2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def bg(rgb):
    return "48" + fg(rgb)[2:]


def style(value):
    """A tmux style as the set of what it says, in any order or case."""
    return set(value.strip().lower().split(","))


def pointed(screen):
    """The highlighted row, else nothing."""
    return next((line for line in screen.split("\n") if line.startswith("› ")), "")


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
        return looks(self.term.screen(colours=True, blank=True).rstrip("\n"))[-2:]

    def off(self, bar, theme):
        """What of the bar is not in `theme`, else None: each cell on the surface but its chip's,
        which are on-accent on the accent, and each part in its role."""
        if len(bar) < 2 or CHIP not in plain(bar[0]) or KEY not in plain(bar[1]):
            return "no bar of a working seat"
        chip = plain(bar[0]).index(CHIP) - 1
        for number, line in enumerate(bar):
            if len(line) != SIZE[0]:
                return f"line {number + 1} is {len(line)} cells"
            for at, (_, shown) in enumerate(line):
                chipped = number == 0 and chip <= at < chip + len(CHIP) + 2
                ground = "accent" if chipped else "surface"
                if bg(theme[ground]) not in shown:
                    return f"line {number + 1}, cell {at + 1} is not on the {ground}: {shown}"
        for text, role, line in (("acme", "text", 0), (MODEL, "muted", 0), (KEY, "dim", 1),
                                 (WORD, "muted", 1), (CHIP, "on-accent", 0)):
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

    def styles(self, theme):
        """tmux's own styles in the seat are `theme`'s: the selection and the position while
        scrolling back are its window's, the message line its session's."""
        for scope, name, ground in (("-wv", "mode-style", "selection"),
                                    ("-v", "message-style", "surface")):
            held = self.home.tmux("show-options", scope, "-t", "=acme:", name)
            self.assertEqual(held.code, 0, held.err)
            self.assertEqual(style(held.out), {f"fg=#{theme['text']}", f"bg=#{theme[ground]}"})

    def choose(self, theme):
        """`theme` chosen on `c`, as the owner chooses it."""
        menu = Terminal(self.home, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait("esc leave", 60)
        menu.keys("c")
        menu.wait(lambda text: "Theme" in text and "esc back" in text, 60)
        while "Theme" not in (row := pointed(menu.screen())):
            menu.keys("Down")
            menu.wait(lambda text: pointed(text) not in ("", row), 30)
        menu.keys("Right", "Space")
        menu.wait(f"● {theme}")

    def test_a_the_bar_stands_on_the_surface_each_part_in_its_role(self):
        self.drawn(BLACK)

    def test_b_tmux_s_own_styles_in_the_seat_are_the_theme_s(self):
        self.drawn(BLACK)
        self.styles(BLACK)

    def test_c_the_popup_is_bordered_in_the_border_colour(self):
        self.popup(BLACK)

    def test_d_a_theme_chosen_on_c_is_the_next_bar_s_and_popup_s(self):
        self.choose("white")
        # choosing writes no seat: its bar and tmux's own styles change in the bar's one write
        said = self.home.tmux("display-message", "-p", "-t", "=acme:",
                              "\t".join(f"#{{{name}}}" for name in STYLES))
        self.assertIn([style(value) for value in said.out.strip().split("\t")],
                      [[style(f"fg=#{theme['text']},bg=#{theme[ground]}")
                        for ground in ("surface", "surface", "selection")]
                       for theme in (BLACK, WHITE)])
        self.drawn(WHITE)
        self.styles(WHITE)
        self.popup(WHITE)

    def test_e_the_popup_is_in_the_theme_config_toml_names_as_the_key_is_pressed(self):
        config = self.home.path / ".agentkit" / "config.toml"     # as another ak's `c` writes it
        text, found = re.subn(r"(?m)^theme\s*=.*$", 'theme = "black"', config.read_text())
        self.assertEqual(found, 1, text)
        config.write_text(text)
        self.popup(BLACK)

    def test_f_a_session_ak_did_not_start_keeps_its_styles(self):
        self.assertEqual(others(self.home), self.others)


if __name__ == "__main__":
    unittest.main()
