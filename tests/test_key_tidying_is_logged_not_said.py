"""What ak tidies by itself as its menu opens goes to the tick's log, and the menu stays on its
seats: a seat retired after its week costs the owner no screen to dismiss (the owner, 10 Nov 2026).

Black-box: ak in a person's terminal beside two live seats and the record of a third that tmux last
saw eight days ago.  The menu forgets the third behind its first frame; `j` then moves the
highlight, which a notice standing in front of the menu would have taken instead.  A log that
cannot take the line leaves it for the owner to read, and the third is forgotten all the same.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

LIVE = ("fix-api", "tidy-docs")
# dated as the tick's own lines are
FORGOT = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d .*forgot the session acme, gone for 8d$",
                    re.MULTILINE)


def seats(home):
    """The two live seats and the week-old record; where that record is."""
    made = int(time.time()) - 600     # rows go in the order their seats were made
    for number, name in enumerate(LIVE):
        Seat(home, name, record={"created": made + number})
    seen = int(time.time()) - 8 * 86400
    Seat(home, "acme", alive=False, record={"created": seen - 86400, "seen": seen})
    return home.path / ".agentkit" / "state" / "session-acme.json"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TidyingIsLogged(unittest.TestCase):
    def test_a_seat_forgotten_as_the_menu_opens_is_logged_and_the_menu_stays(self):
        with Home() as home:
            record = seats(home)
            menu = Terminal(home)
            menu.wait(lambda screen: f"1  {LIVE[0]}" in screen and f"2  {LIVE[1]}" in screen)
            menu.wait(lambda _: not record.exists())
            menu.keys("j")
            menu.wait(f"› 2  {LIVE[1]}")
            log = home.path / ".agentkit" / "tmp" / "watch.log"
            self.assertRegex(log.read_text(encoding="utf-8"), FORGOT)
            menu.keys("Escape")
            self.assertEqual(menu.exit_code(), 0)

    def test_a_line_the_log_cannot_take_is_the_owners_and_the_seat_still_goes(self):
        with Home() as home:
            record = seats(home)
            (home.path / ".agentkit" / "tmp" / "watch.log").mkdir(parents=True)  # takes no line
            menu = Terminal(home)
            menu.wait("WARN not logged")
            menu.wait(lambda _: not record.exists())
            menu.keys("Escape")       # the notice
            menu.wait(lambda screen: f"› 1  {LIVE[0]}" in screen and f"2  {LIVE[1]}" in screen)
            menu.keys("Escape")
            self.assertEqual(menu.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
