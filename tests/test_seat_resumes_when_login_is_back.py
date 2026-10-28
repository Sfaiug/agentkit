"""A seat stopped on its harness's login words is typed past them once its login works again.

A login can fail for a minute and come back by itself, and a turn that ended on it leaves the
seat at its prompt with its work half done.  The tick asks the harness's `auth` verb whenever a
seat shows that harness's login words, whatever else they say: while the verb refuses, the seat
reads `needs you` and nothing is typed into it, however long it stands; once the verb passes,
the seat is typed past the words with its harness's resume keys, once, after the three minutes
any passing error stands, and nothing more while those words stand, on the same screen or one
redrawn around them.  The stall's clock is set back as ak keeps it, not waited out.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each tick in the
box `home.tick()` builds, before seats of tests/fixtures/akseat.py showing a real Claude pane
stopped on its login words, one with the row Claude draws under its footer for seconds at a
time, on a fake harness from tests/fixtures/fakeadapter.py whose `auth` verb the test refuses
and passes.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat

STOOD = 240     # past the three minutes an error stands before anything is typed
SCREEN = (FIXTURES / "claude-auth-401-pane.txt").read_text()
# the same turn ended on another of the harness's own login words, with no `log in` among them
BARE = SCREEN.replace("Please run /login · API Error: 401 Invalid API key", "Invalid API key")
# a real turn's login error, under it the tip Claude Code shows while tmux's focus-events is off
TIP = (FIXTURES / "claude-auth-401-tmux-tip-pane.txt").read_text()


def state(home, name):
    return json.loads((home.path / ".agentkit" / "state" / name).read_text())


def stood(home):
    """Every seat's stall, as ak keeps it, set back as if its screen had stood STOOD seconds."""
    watched = state(home, "watch.json")
    for stall in watched["stalls"].values():
        stall["since"] = time.time() - STOOD
    home.write(".agentkit/state/watch.json", watched)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class LoginBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        claude = fakeadapter.install(home, claude="pass")["claude"]
        cls.seats = seats = [Seat(home, "acme", screen=SCREEN), Seat(home, "beta", screen=BARE),
                             Seat(home, "gamma", screen=TIP)]
        claude.answer("auth", "token expired", 1)
        cls.ticks = [home.tick()]
        stood(home)
        cls.ticks.append(home.tick())
        cls.refused = [(state(home, f"seat-{seat.name}.json")["word"], seat.lines())
                       for seat in seats]
        claude.answer("auth", "logged in: ~/.claude/.credentials.json", 0)
        cls.ticks.append(home.tick())
        cls.back = [seat.lines() for seat in seats]
        stood(home)
        cls.ticks.append(home.tick())
        cls.resumed = [seat.wait_lines(1) for seat in seats]
        stood(home)
        cls.ticks.append(home.tick())
        cls.again = [seat.lines() for seat in seats]
        for seat in seats:
            seat.show(seat.screen.replace("\n\n❯ Say OK", "\n\n\n❯ Say OK", 1))
        cls.ticks.append(home.tick())
        stood(home)
        cls.ticks.append(home.tick())
        cls.redrawn = [seat.lines() for seat in seats]

    def test_every_tick_succeeds(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.err)

    def test_a_login_still_refused_needs_you_and_nothing_is_typed(self):
        self.assertEqual(self.refused, [("needs you", [])] * 3)

    def test_a_login_that_works_again_is_typed_past_once_after_the_wait(self):
        self.assertEqual(self.back, [[]] * 3)
        self.assertEqual(self.resumed, [["continue"]] * 3)

    def test_the_next_tick_on_the_same_screen_types_nothing_more(self):
        self.assertEqual(self.again, [["continue"]] * 3)

    def test_a_screen_redrawn_around_the_same_words_types_nothing_more(self):
        self.assertEqual(self.redrawn, [["continue"]] * 3)


if __name__ == "__main__":
    unittest.main()
