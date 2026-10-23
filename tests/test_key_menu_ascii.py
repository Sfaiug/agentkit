"""Without a UTF-8 locale the menu's key line is ASCII, `j/k move   enter open` leading it, and
`>` marks the highlighted seat, whose row is ASCII too; LC_ALL, when set, decides over LANG.

A terminal started in the C or POSIX locale may draw `↑`, `⏎` and `›` as nothing or as noise,
and the person there must still read what each key does.  The locale is the one the program is
started with: LC_ALL when it is set, else LANG.  Black-box: the menu runs in a person's terminal
(tests/fixtures/akterm.py) beside a seat of tests/fixtures/akseat.py, and this test fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

ASCII_KEYS = "  j/k move   enter open   n new   x stop   c config   esc leave"
UTF8_KEYS = "  ↑↓ move   ⏎ open   n new   x stop   c config   esc leave"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MenuAscii(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()       # its own locale is C.UTF-8, in LANG and LC_ALL alike
        cls.addClassCleanup(cls.home.close)
        Seat(cls.home, "fix-api", screen="claude-working-pane.txt")

    def menu(self, locale):
        """The screen once the seat's row and the key line are up, and the seat's row; Esc
        then leaves."""
        term = Terminal(self.home, size=(100, 30), env=locale)
        screen = term.wait(lambda shown: "esc leave" in shown and " fix-api " in shown)
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)
        rows = [row.rstrip() for row in screen.split("\n")]
        return rows, next(row for row in rows if " fix-api " in row)

    def test_a_c_or_posix_locale_gets_the_ascii_key_line_and_highlight(self):
        for locale in ({"LANG": "C", "LC_ALL": "C"},
                       {"LC_ALL": "C"},                         # over the UTF-8 LANG
                       {"LANG": "C", "LC_ALL": ""},             # an empty LC_ALL is unset
                       {"LANG": "POSIX", "LC_ALL": ""}):
            with self.subTest(locale):
                rows, seat = self.menu(locale)
                self.assertIn(ASCII_KEYS, rows)
                self.assertNotIn("›", "\n".join(rows))
                self.assertTrue(seat.startswith(">"), seat)
                self.assertTrue(seat.isascii(), seat)

    def test_a_utf8_lc_all_outranks_a_c_lang(self):
        rows, seat = self.menu({"LANG": "C"})
        self.assertIn(UTF8_KEYS, rows)
        self.assertTrue(seat.startswith("›"), seat)


if __name__ == "__main__":
    unittest.main()
