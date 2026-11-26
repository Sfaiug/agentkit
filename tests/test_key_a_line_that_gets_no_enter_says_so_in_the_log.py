"""A line that gets no Enter says so in the tick's log, on one line.

ak gives a line it typed into a seat its Enter only once the seat's composer reads as that line
alone.  On 26 Nov 2026 a line sat four minutes over a row its adapter did not know, its read
never matching, and the log held nothing of it.  Here a seat is owed a line holding a line
separator, which is no key and so is typed as it is, and its pane draws nothing typed into it:
one tick types the line and no Enter, and prints one line naming the seat and the line's first
60 characters, a space in the separator's place: left in, it would end the log's line.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
tick in the box `home.tick()` builds, before a seat of tests/fixtures/akseat.py at Claude
Code's prompt, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

LINE = "run 20261126-0900-fix-api ended PASS,\u2028merged as https://github.com/acme/api/pull/42."
SAID = ("WARN acme: its composer does not read as the line typed, so no Enter: "
        "run 20261126-0900-fix-api ended PASS, merged as https://gith")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ALineThatGetsNoEnter(unittest.TestCase):
    def test_a_tick_types_the_line_and_no_enter_and_says_so_once_on_one_line(self):
        home = Home()
        self.addCleanup(home.close)
        # a composer mark its screen holds nowhere: the pane draws nothing typed into it
        seat = Seat(home, "acme", model="opus", composer="drawn nowhere")
        home.write(".agentkit/state/seat-acme.json", {"owed_lines": [{"id": "1", "line": LINE}]})
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(seat.typed(), LINE)
        self.assertEqual([row for row in done.out.splitlines() if "no Enter" in row], [SAID])


if __name__ == "__main__":
    unittest.main(verbosity=2)
