"""Ctrl-b m hands the menu over a seat its terminal's colour: the two menus are of one look.

The owner (24 Nov 2026), of the menu in its own window and the one over a session: "the colors
are different here and there. This should not be. [...] Have 100% consistency, they should take
the color from the same code."  A menu keeps its terminal's answer as `light` or `dark` and the
colour after it; the key reads that once as it is pressed and, where the look reads on the colour
(tests/test_the_look_reads.py), frames the popup in the look's border on it and hands the menu
the colour, which draws in the look there: the band and the rule the menu in its own window has
on that terminal, every other cell painted the colour, as the terminal a seat is seen from may
not be the one that answered.  Whatever is kept meanwhile reaches only the next popup.  Where
only a word, nothing, or a colour the look does not read on is kept, frame and menu are as they
were, and so is what no colour is handed: the form an older binding asks themes.py in, and
`ak attach --overlay` run by hand.

Black-box, through tests/fixtures/akterm.py: a seat ak opens, a fake `claude` in it, attached in
a person's terminal of 24-bit colour, whose background a test sets, and the menu in its own
window on another; each cell judged by how it looks (tests/fixtures/aklooks.py).  It compares the
colours, not the screens cell for cell: they differ in size.  The tests run in their order.
"""

import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.aklooks import ATTRIBUTES, look, plain, settled
from fixtures.akterm import KEPT, SERVER, Terminal, forget

DARK, LIGHT, GREY = "203040", "e8e4d8", "808080"    # terminals' own: the look reads on two
# each theme's background, selection and border, as a menu painted in it draws them
BLACK, WHITE = ("000000", "08305d", "3a3f46"), ("ffffff", "dcecff", "b1b8c0")
BORDER_DIM = "3a3f46 868d97"     # black's border and dim, as themes.py's first form says them


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def part(shown, ground):
    """A look's colour on that ground, 38 its text's, 48 its background's: none, or itself."""
    return frozenset(p for p in shown if p.startswith(ground + ";"))


def drawn(rows):
    """What a menu's cells, `rows` of looks, are in: the rule, the colour of its row of `─`; the
    band, the backgrounds of its `›` row across the columns the rule spans, as wide as the menu;
    and the backgrounds of every other cell."""
    rules = [row for row in rows if set(plain(row).strip()) == {"─"}]
    [rule] = {part(shown, "38") for row in rules for char, shown in row if char == "─"}
    start, end = plain(rules[0]).index("─"), plain(rules[0]).rindex("─") + 1
    at = next(at for at, row in enumerate(rows) if "›" in plain(row))
    grounds = [[part(shown, "48") for _, shown in row] for row in rows]
    rest = {ground for row, line in enumerate(grounds) for cell, ground in enumerate(line)
            if row != at or not start <= cell < end}
    return {"plain": rest, "band": set(grounds[at][start:end]), "rule": rule}


def today(theme):
    """What a popup painted in `theme` is in, its frame in the theme's border and on nothing."""
    frame = frozenset({sgr(theme[2])})
    return {"plain": {frozenset({sgr(theme[0], "48")})}, "band": {frozenset({sgr(theme[1], "48")})},
            "rule": frame, "corner": frame, "title": frame}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CtrlBMHandsTheMenuItsTerminalsColour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
        # its tmux starts here, and what that starts with is its popup's: no NO_COLOR
        done = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", tty=True,
                       env={"NO_COLOR": None})
        assert done.code == 0, done.err
        Terminal(home, "--help").exit_code()    # its tmux keeps a background only while it is up

    def open(self, *args, background, env=None):
        """`args` run on a true-colour terminal of that background."""
        done = self.home.tmux("set-option", "-g", "window-style", f"bg=#{background}",
                              server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        term = Terminal(self.home, *args, size=(100, 30),
                        env={"COLORTERM": "truecolor", **(env or {})})
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        return term

    def menu(self, background):
        """What a menu run in its own window on that background, which it keeps, draws in."""
        menu = self.open(background=background)
        shown = drawn(settled(menu, "esc leave", bound=60))
        self.home.tmux("kill-session", "-t", menu.pane, server=SERVER)
        return shown

    def up(self, background=DARK):
        """Ctrl-b m's popup over the seat, seen from a terminal of that background."""
        seat = self.open("orch", "acme", background=background)
        seat.wait("Ctrl-b m", 60)               # its bar is up: the seat has the keys
        seat.keys("C-b", "m")
        return seat

    def popup(self, seat, shown=lambda text: "esc leave" in text):
        """What the popup up on `seat` is in, once it shows `shown`: its frame's corner and
        title, and what its menu draws inside the frame (`drawn`)."""
        rows = settled(seat, shown, bound=60)
        top = next(at for at, row in enumerate(rows) if "╭" in plain(row))
        bottom = next(at for at, row in enumerate(rows) if "╰" in plain(row))
        inside = [row[plain(row).index("│") + 1:plain(row).rindex("│")]
                  for row in rows[top + 1:bottom]]
        return {**drawn(inside), **{name: frozenset(look([rows[top]], text) - ATTRIBUTES)
                                    for name, text in (("corner", "╭"), ("title", "agentkit"))}}

    def down(self, seat):
        seat.keys("Escape")
        seat.wait(lambda screen: "esc leave" not in screen, 30)

    def framed(self, background, menu):
        """What a popup is in after a menu on `background` drew `menu`: in its look, painted."""
        on = menu["rule"] | {sgr(background, "48")}
        return {**menu, "plain": {frozenset({sgr(background, "48")})}, "corner": on, "title": on}

    def test_a_after_a_menu_ran_on_a_colour_the_popup_is_in_its_look_painted(self):
        menu = self.menu(DARK)
        self.assertEqual(menu["plain"], {frozenset()})       # on its terminal's own
        [rule] = menu["rule"]
        for seen in (DARK, "".join(f"{int(c):02x}" for c in rule.split(";")[2:])):
            with self.subTest(seen_from=seen):      # the frame's own colour on a terminal of it
                seat = self.up(seen)
                self.assertEqual(self.popup(seat), self.framed(DARK, menu))
                self.down(seat)

    def test_b_a_colour_kept_while_it_is_up_reaches_only_the_next_popup(self):
        dark = self.framed(DARK, self.menu(DARK))
        seat = self.up()
        self.assertEqual(self.popup(seat), dark)
        light = self.framed(LIGHT, self.menu(LIGHT))
        self.assertNotEqual(light, dark)
        seat.keys("c")                  # another screen, then the menu drawn again whole
        seat.wait("esc back", 30)
        seat.keys("Escape")
        self.assertEqual(self.popup(seat, lambda text: "esc leave" in text
                                    and "esc back" not in text), dark)
        self.down(seat)
        seat.keys("C-b", "m")
        self.assertEqual(self.popup(seat), light)
        self.down(seat)

    def test_c_a_word_alone_nothing_or_a_colour_the_look_does_not_read_on_is_as_today(self):
        for kept, theme in (("dark", BLACK), (None, BLACK), (GREY, WHITE)):
            with self.subTest(kept=kept):
                if kept == GREY:
                    self.menu(GREY)                 # white's dim text has too little on it
                elif kept:
                    self.home.write(KEPT, f"{kept}\n")
                else:
                    forget(self.home)
                seat = self.up()
                self.assertEqual(self.popup(seat), today(theme))
                self.down(seat)

    def test_d_with_a_colour_kept_what_is_handed_none_is_as_today(self):
        self.home.write(KEPT, f"dark {DARK}\n")
        said = subprocess.run([sys.executable, "-S", "-I", str(REPO / "agentkit" / "themes.py"),
                               str(self.home.path / ".agentkit" / "config.toml"), "border", "dim"],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual((said.returncode, said.stdout), (0, BORDER_DIM + "\n"), said.stderr)
        overlay = self.open("attach", "--overlay", background=DARK,
                            env={"AGENTKIT_SESSION": "acme", "AGENTKIT_PADDING": "1"})
        shown = drawn(settled(overlay, "esc leave", bound=60))
        self.assertEqual(shown, {name: today(BLACK)[name] for name in shown})


if __name__ == "__main__":
    unittest.main()
