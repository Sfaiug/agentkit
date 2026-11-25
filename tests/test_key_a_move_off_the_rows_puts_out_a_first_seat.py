"""The pointer moving off every row puts the keys' highlight out, on a screen a draw gave its
first row since the pointer last moved too.

The ak screen with no seat, its one provider free so no meter is on it either, has no row the
pointer could take the highlight off.  A seat coming up there is lit by the keys, and the pointer
moving on along the header puts that out, as on a screen that had rows all along
(tests/test_key_pointer_only_on_what_is_drawn.py).  Black-box: the program `AK_BIN` names runs
in a person's terminal (tests/fixtures/akterm.py) with no colour, so a row's `›` is the
highlight, over a seat (tests/fixtures/akseat.py) and a faked harness
(tests/fixtures/fakeadapter.py); the pointer's moves are typed as the SGR reports a terminal
sends.
This test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


def point(col, row):
    return f"\x1b[<35;{col};{row}M"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FirstSeat(unittest.TestCase):
    def test_a_move_along_the_header_puts_out_the_first_seat(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, {"fable": "claude"}, providers={"anthropic": {"mode": "free"}})
        term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("no sessions", bound=25)
        term.type(point(8, 1))                      # the header, of a screen with no row
        settled(term, "no sessions", bound=25)
        Seat(home, "acme", model="fable")
        term.wait(lambda screen: "› 1  acme" in screen, bound=45)
        term.type(point(9, 1))                      # on along the header
        rows = [plain(line) for line in settled(term, "acme", bound=25) if "acme" in plain(line)]
        self.assertEqual([row for row in rows if row.startswith("›")], [], rows)


if __name__ == "__main__":
    unittest.main()
