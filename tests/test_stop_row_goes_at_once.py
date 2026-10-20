"""`x` takes a seat's row off the screen at once and stops the seat behind it: no read puts the row
back while the stop goes, nor offers it as past or by its number, a refused stop says why and
gives the row back, and the popup stops any seat as the owner and goes before its own seat's
stop ends, what refuses that one said by the next menu.

Each test runs the real menu loop on a pty of its own through tests/test_close_and_info.py's
`Menu`, the stop a process of its own that waits while the test holds it; nothing here stops a
real seat, and the only processes signalled are the test's own children.
"""

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import terminal
from test_close_and_info import ENTER, Menu


def without(menu, name, after):
    """Where in the menu's output the first whole screen without `name` begins, after `after`."""
    def ready(text):
        for home in re.finditer(r"\x1b\[H", text[after:]):
            screen, ended, _ = text[after + home.end():].partition("\x1b[J")
            screen = terminal.ANSI.sub("", screen)
            if ended and menu.leave_key in screen and name not in screen:
                return after + home.start()
        return None
    return menu.until(ready, f"a screen without {name}")


class StopBehindTheRow(unittest.TestCase):
    def setUp(self):
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        self.hold = Path(held.name) / "hold"
        self.hold.touch()                 # the stop waits until this is gone

    def test_the_row_goes_before_the_stop_ends_and_no_read_brings_it_back(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, hold=self.hold)
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        gone = without(menu, "omega", mark)
        self.assertNotIn("<stopped", menu.text())
        # a read while the stop is held: alpha's word moves with it, and omega stays off
        menu.seats.write_text(json.dumps({"alpha": "needs you", "omega": "done"}))
        moved = menu.seats.parent / ".agentkit" / "state" / "runs-moved"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.touch()
        menu.frame(lambda lines: any("alpha" in line and "needs you" in line for line in lines),
                   after=gone)
        self.assertNotIn("<stopped", menu.text())
        self.hold.unlink()
        menu.saw("<stopped omega>", after=gone)
        menu.leave()
        rest = terminal.ANSI.sub("", menu.text()[gone:]).replace("<stopped omega>", "")
        self.assertNotIn("omega", rest)

    def test_a_refused_stop_says_why_and_its_row_comes_back(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, refuse=True)
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        menu.saw("stop: omega refused", after=mark)
        back = menu.mark()
        menu.send(ENTER)
        menu.frame(lambda lines: any("omega" in line for line in lines), after=back)
        menu.leave()

    def read(self, menu, seats):
        """The seats as `seats` has them, read anew by the menu up."""
        menu.seats.write_text(json.dumps(seats))
        moved = menu.home / ".agentkit" / "state" / "runs-moved"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.touch()

    def test_a_held_stop_is_offered_nowhere_until_it_ends(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, hold=self.hold)
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        gone = without(menu, "omega", mark)
        # read as the stop marks it stopped, before the stop has ended: still not past
        self.read(menu, {"alpha": "needs you", "omega": "stopped"})
        lines = menu.frame(lambda lines: any("needs you" in line for line in lines), after=gone)
        self.assertNotIn("p past", lines[-1])
        menu.send(b"2")                   # nor its number's to open
        menu.saw("no session 2", after=gone)
        self.assertNotIn("<opened", menu.text())
        menu.send(ENTER)
        self.hold.unlink()
        menu.saw("<stopped omega>", after=gone)
        menu.leave()

    def test_the_popup_stops_any_seat_as_the_owner(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="alpha")
        menu.frame(lambda lines: "alpha" in menu.highlighted(lines))
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        menu.send(b"x")
        menu.saw("<stopped omega>")       # another seat's, which a seat could not stop
        menu.leave()

    def test_the_popup_over_its_own_seat_goes_before_the_stop_ends(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="omega", hold=self.hold)
        menu.frame()
        menu.send(b"x")
        self.assertEqual(menu.proc.wait(15), 0, menu.text()[-3000:])
        self.assertNotIn("<stopped", menu.text())
        self.hold.unlink()
        menu.saw("<stopped omega>")       # and the stop goes on without it

    def test_what_refuses_the_popups_own_stop_is_the_next_menus_notice(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="omega", refuse=True,
                    hold=self.hold)
        menu.frame()
        menu.send(b"x")
        self.assertEqual(menu.proc.wait(15), 0, menu.text()[-3000:])
        self.hold.unlink()
        menu.saw("<refused omega>")       # left for the next menu, the popup gone
        after = Menu(self, {"alpha": "working", "omega": "done"}, home=menu.home)
        after.saw("stop: omega refused")
        after.send(ENTER)
        after.frame(lambda lines: any("omega" in line for line in lines))
        after.leave()

    def test_a_stop_that_cannot_start_says_so_and_the_popup_stays(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="omega",
                    python=str(self.hold.parent / "no-python"))
        menu.frame()
        menu.send(b"x")
        menu.saw("no-python")
        self.assertIsNone(menu.proc.poll())
        menu.send(ENTER)
        menu.frame(lambda lines: any("omega" in line for line in lines))
        menu.leave()

if __name__ == "__main__":
    unittest.main()
