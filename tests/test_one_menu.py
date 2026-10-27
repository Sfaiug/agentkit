"""Ctrl-b m is the main screen: the popup draws the menu's own key line, `x` added, its highlight
starts on the seat it is over, and `x` and `c` act on the seat the popup is over, whichever is
highlighted (tests/test_key_x_stops_only_its_own_seat.py, tests/test_key_config_scope.py).

The owner (20 Oct 2026): "There should be no differentiation between the full menu screen, or
the menu screen when opened from inside a session."  And on 24 Oct 2026: "when inside a session
and I open the menu, only that session models should be able to be edited … when I open a new
ak window … and go in the config, the changes I make should just reflect the next default
settings for new sessions I start."  And on 27 Oct 2026: "pressing x should always only apply
to the session in which we are in."  The real loop runs in a child on a pty of
its own through tests/test_close_and_info.py's Menu, with the seats, the stop and `c` faked, in
a throwaway HOME.  Nothing here starts a seat or signals any process but the test's own child.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_close_and_info  # noqa: E402
from test_close_and_info import ESC, Menu  # noqa: E402

# `c` says which seat it was handed, and goes back at once
CHILD = test_close_and_info.CHILD.replace("sys.exit(menu.loop(", (
    "menu.show_config = lambda dry_run, keyboard, session: print(f'<config {session}>', "
    "flush=True)\nsys.exit(menu.loop("), 1)
SEATS = {"alpha": "working", "omega": "working", "gone": "stopped"}


class OneMenu(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(test_close_and_info, "CHILD", CHILD))

    def test_the_popup_draws_the_menus_key_line_its_highlight_on_its_own_seat(self):
        main = Menu(self, SEATS)
        keys = main.frame()[-1]
        main.leave()
        self.assertIn("p past", keys)
        popup = Menu(self, SEATS, own="omega")
        lines = popup.frame()
        self.assertIn("omega", popup.highlighted(lines))
        self.assertEqual(lines[-1], keys.replace("n new", "n new   x stop"))
        popup.leave()

    def test_x_and_c_in_the_popup_act_on_its_own_seat(self):
        popup = Menu(self, SEATS, own="alpha")
        popup.frame(lambda lines: "alpha" in popup.highlighted(lines))
        popup.send(b"j")
        popup.frame(lambda lines: "omega" in popup.highlighted(lines))
        mark = popup.mark()
        popup.send(b"x")
        asked = popup.frame(keys="esc back", after=mark)
        self.assertIn("  Stop alpha and everything it runs?", asked)
        mark = popup.mark()
        popup.send(ESC)                   # kept, and the popup is still up
        popup.frame(lambda lines: "alpha" in popup.highlighted(lines), after=mark)
        popup.send(b"j")
        popup.frame(lambda lines: "omega" in popup.highlighted(lines), after=mark)
        popup.send(b"c")
        popup.saw("<config alpha>", after=mark)
        popup.leave()
        self.assertNotIn("<stopped", popup.text())


if __name__ == "__main__":
    unittest.main()
