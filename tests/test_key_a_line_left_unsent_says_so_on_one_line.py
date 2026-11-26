"""A line two Enters leave unsent says so in the tick's log, on one line.

ak gives a line it typed into a seat a second Enter where the first leaves it in the composer,
and after that names the line in the log's warning.  Here a seat is owed a line holding a line
separator, which is no key and so is typed as it is, and its harness keeps the line: entered,
it draws the line back in its composer and takes no key after.  One tick types the line and
two Enters, and prints one line naming the seat and the line's first 60 characters, a space
in the separator's place: left in, it would end the log's line, one warning read as two.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
tick in the box `home.tick()` builds, before a seat of tests/fixtures/akseat.py at Claude
Code's prompt, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat

LINE = "run 20261126-0900-fix-api ended PASS, merged as https://github.com/acme/api/pull/42."
SAID = ("WARN acme: typed text sits unsent in its composer: "
        "run 20261126-0900-fix-api ended PASS, merged as https://gith")
# the prompt with the line in its composer as the pane draws it, a separator being no character
# it prints: the card its harness shows once the line is entered, taking every key but a `1`
KEPT = (FIXTURES / "claude-prompt-pane.txt").read_text(encoding="utf-8").replace(
    "❯ \n", f"❯ {LINE.replace(chr(0x2028), '')}\n")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ALineLeftUnsent(unittest.TestCase):
    def test_a_tick_types_the_line_and_two_enters_and_says_so_once_on_one_line(self):
        home = Home()
        self.addCleanup(home.close)
        seat = Seat(home, "acme", model="opus", asks={"run ": KEPT})
        home.write(".agentkit/state/seat-acme.json", {"owed_lines": [{"id": "1", "line": LINE}]})
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(seat.typed(), LINE + "\r\r")
        self.assertEqual([row for row in done.out.splitlines() if "unsent" in row], [SAID])


if __name__ == "__main__":
    unittest.main(verbosity=2)
