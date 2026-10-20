"""`x` takes a seat's row off the screen at once and stops the seat behind it: no read puts the row
back while the stop goes, nor offers it as past or by its number, a refused stop says why and
gives the row back, and the popup stops any seat as the owner, staying up to say a refusal.

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

    def test_a_held_stop_is_offered_nowhere_until_it_ends(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, hold=self.hold)
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        gone = without(menu, "omega", mark)
        self.assertNotIn("p past", menu.frame(after=gone)[-1])   # not stopped yet: not past
        menu.send(b"2")                   # nor its number's to open
        menu.saw("no session 2", after=gone)
        self.assertNotIn("<opened", menu.text())
        menu.send(ENTER)
        self.hold.unlink()
        menu.saw("<stopped omega>", after=gone)
        menu.leave()

    def test_the_popup_stops_any_seat_as_the_owner_and_stays_up_to_say_a_refusal(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="alpha")
        menu.frame(lambda lines: "alpha" in menu.highlighted(lines))
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        menu.send(b"x")
        menu.saw("<stopped omega>")       # another seat's, which a seat could not stop
        menu.leave()
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="omega", refuse=True)
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        menu.saw("stop: omega refused", after=mark)
        self.assertIsNone(menu.proc.poll())
        menu.send(ENTER)
        menu.leave()

if __name__ == "__main__":
    unittest.main()
