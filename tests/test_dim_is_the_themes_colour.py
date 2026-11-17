"""What is dim is drawn in the theme's `dim`, never fainter than it.

The owner (12 Nov 2026) gave each theme its `dim`, #6f757e in white and #868d97 in black, and
(10 Nov 2026): "Only ever use these colors to color everythign inside ak."  A terminal draws a
faint cell (SGR 2) darker than its colour, about half way to the background: a colour of neither
theme, and on black one too near the background to read.  So above eight colours a dim cell is
its role's colour alone, and nothing ak draws is faint; at eight colours, which hold no grey of
the theme's, a note stays faint.  The ak screen and `c` drawn in-process on a true-colour terminal
as tests/test_news_motion.py draws them, each frame played cell by cell, in each theme.
"""

import re
import unittest
from unittest.mock import patch

from test_moving_lights_are_the_rainbow import Screens, played
from test_news_motion import Keyboard
from agentkit import config, menu, terminal
from agentkit.themes import ROLES

SGR = re.compile(r"\x1b\[([\d;]*)m")
NEAREST = {"6f757e": 243, "868d97": 245}     # each theme's dim, the nearest of xterm's 256


def faint(text):
    """Whether any code in `text` turns on the faint attribute: a `2` that is no colour's part."""
    for found in SGR.finditer(text):
        codes = found.group(1).split(";")
        while codes:
            code = codes.pop(0)
            if code in ("38", "48") and codes[:1] in (["2"], ["5"]):
                codes = codes[4 if codes[0] == "2" else 2:]
            elif code == "2":
                return True
    return False


class DimIsTheThemesColour(Screens):
    def themes(self, check):
        """`check(dim)` in each theme, `dim` its colour as `rrggbb`."""
        for theme in (terminal.WHITE, terminal.BLACK):
            self.now = 1000.0
            with self.subTest(theme=theme), patch.object(terminal, "THEME", theme):
                check(ROLES["dim"][theme])

    def test_above_eight_colours_dim_is_its_colour_alone_and_needs_you_still_bold(self):
        def check(dim):
            for depth, ink in ((24, "38;2;" + ";".join(map(str, bytes.fromhex(dim)))),
                               (256, f"38;5;{NEAREST[dim]}")):
                with patch.object(terminal, "colour_depth", return_value=depth):
                    for kind in ("dim", "idle", "waiting"):
                        self.assertEqual(terminal.styled("a note", kind),
                                         f"\033[{ink}ma note\033[0m", (depth, kind))
                    self.assertTrue(terminal.styled("!", "needs you").startswith("\033[1;"))
        self.themes(check)

    def test_at_eight_colours_a_note_is_faint_as_before(self):
        with patch.object(terminal, "colour_depth", return_value=8):
            self.assertEqual(terminal.styled("a note", "dim"), "\033[2ma note\033[0m")
            for kind in ("idle", "waiting"):
                self.assertEqual(terminal.styled("a note", kind), "\033[2;37ma note\033[0m")

    def test_the_ak_screen_and_c_over_an_idle_seat_hold_nothing_faint(self):
        config.save_session(self.cfg, "fix-api", "opus", ["astra"], {"cwd": "/", "created": 0})

        def check(dim):
            self.words = {"fix-api": "idle"}
            waits, _ = self.run_menu([])
            self.assertFalse([text for *_, text in waits if faint(text)], "the ak screen")
            screen = played(waits)[-1][2]
            self.assertIn("idle", "".join(glyph for glyph, _ in screen.values()))
            [(row, column)] = self.cells(screen, " fix-api ", r"\d")
            self.assertEqual(screen[row, column], ("1", dim), "the seat's number")
            with patch.object(terminal, "taken", return_value=True):
                waits, _ = self.run_menu([None] * 3, 1, lambda: menu.show_config(
                    False, Keyboard(), "fix-api"))
            self.assertIn("Opus 5.5", terminal.plain("".join(text for *_, text in waits)))
            self.assertFalse([text for *_, text in waits if faint(text)], "`c`")
        self.themes(check)


if __name__ == "__main__":
    unittest.main(verbosity=2)
