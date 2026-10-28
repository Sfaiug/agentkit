"""A seat stopped on its harness's login words is typed past them once its login works again.

A login can fail for a minute and come back by itself, and a turn that ended on it leaves the
seat at its prompt with its work half done.  The tick asks the harness's `auth` verb whenever a
seat shows that harness's login words: while the verb refuses, the seat reads `needs you` and
nothing is typed into it, however long it stands; once the verb passes, the seat is typed past
the words with its harness's resume keys, once, after the three minutes any passing error
stands, and the next tick on the same screen types nothing more.  The stall's clock is set back
as ak keeps it, not waited out.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, each tick in the box `home.tick()` builds, before a seat of
tests/fixtures/akseat.py showing a real Claude pane stopped on its login words, on a fake
harness from tests/fixtures/fakeadapter.py whose `auth` verb the test refuses and passes.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

STOOD = 240     # past the three minutes an error stands before anything is typed


def state(home, name):
    return json.loads((home.path / ".agentkit" / "state" / name).read_text())


def stood(home):
    """The seat's stall, as ak keeps it, set back as if its screen had stood STOOD seconds."""
    watched = state(home, "watch.json")
    watched["stalls"]["acme"]["since"] = time.time() - STOOD
    home.write(".agentkit/state/watch.json", watched)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class LoginBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        claude = fakeadapter.install(home, claude="pass")["claude"]
        cls.seat = seat = Seat(home, "acme", screen="claude-auth-401-pane.txt")
        claude.answer("auth", "token expired", 1)
        cls.ticks = [home.tick()]
        stood(home)
        cls.ticks.append(home.tick())
        cls.refused = state(home, "seat-acme.json")["word"], seat.lines()
        claude.answer("auth", "logged in: ~/.claude/.credentials.json", 0)
        cls.ticks.append(home.tick())
        cls.back = seat.lines()
        stood(home)
        cls.ticks.append(home.tick())
        cls.resumed = seat.wait_lines(1)
        stood(home)
        cls.ticks.append(home.tick())
        cls.again = seat.lines()

    def test_every_tick_succeeds(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.err)

    def test_a_login_still_refused_needs_you_and_nothing_is_typed(self):
        self.assertEqual(self.refused, ("needs you", []))

    def test_a_login_that_works_again_is_typed_past_once_after_the_wait(self):
        self.assertEqual(self.back, [])
        self.assertEqual(self.resumed, ["continue"])

    def test_the_next_tick_on_the_same_screen_types_nothing_more(self):
        self.assertEqual(self.again, ["continue"])


if __name__ == "__main__":
    unittest.main()
