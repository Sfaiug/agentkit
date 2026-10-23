"""No page goes for a question while the owner is in its seat, nor in the minute after they left.

The owner is paged for an unanswered question, never while in that seat: they are reading it
there, and a seat works on with its question standing, so a look at it must not count as an
answer either.  The tick holds a question's page back for a minute from the owner's last move
in the seat, an open or a key, though they left between two ticks; a seat nobody opened in that
minute is paged in the very same tick.  Three seats ask the same question, idle a minute: the
owner opens one and stays, opens another and leaves, and leaves the third alone.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its tick in the box
`home.tick()` builds, the owner opens a seat with `ak orch NAME` in a terminal of
tests/fixtures/akterm.py, and pages land in tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from fixtures.sink import Sink

QUESTION = "Which database should the app use?"
MINUTE = 60
STAYS, LEFT, AWAY = "acme", "beta", "gamma"


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


def clients(home):
    """The seats a terminal is attached to now."""
    return home.tmux("list-clients", "-F", "#{session_name}").out.split()


def opened_by_owner(home, name):
    """The owner opens that seat from their terminal with `ak orch NAME`, and is in it."""
    terminal = Terminal(home, "orch", name)
    deadline = time.monotonic() + 30
    while name not in clients(home):
        assert time.monotonic() < deadline, terminal.screen()
        time.sleep(0.05)
    return terminal


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OwnerInTheSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(home, ["opus"])
        for name in (STAYS, LEFT, AWAY):
            Seat(home, name)
        opened = time.monotonic()
        # tmux keeps when someone last typed in or opened a seat, and nothing back-dates it:
        # the seats sit out the owner's minute in real time, once.
        time.sleep(max(0.0, opened + MINUTE + 0.5 - time.monotonic()))
        for name in (STAYS, LEFT, AWAY):
            home.write(f".agentkit/state/notify-{name}.json",
                       {"session": name, "kind": "needs", "text": QUESTION,
                        "time": time.time() - 300})
        opened_by_owner(home, STAYS)
        left = opened_by_owner(home, LEFT)
        left.keys("C-b", "d")
        assert left.exit_code() == 0, left.screen()
        assert clients(home) == [STAYS], clients(home)
        done = home.tick()
        assert done.code == 0, done.out + done.err

    def test_no_page_goes_while_the_owner_is_in_the_seat(self):
        self.assertNotIn(f"🙋 Needs you · {STAYS}", self.sink.pages())
        card = state(self.home, f"card-{STAYS}.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", False))

    def test_none_goes_in_the_minute_after_they_left_it(self):
        self.assertNotIn(f"🙋 Needs you · {LEFT}", self.sink.pages())
        card = state(self.home, f"card-{LEFT}.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", False))

    def test_the_seat_they_did_not_open_is_paged_in_the_same_tick(self):
        self.assertEqual(self.sink.pages(), [f"🙋 Needs you · {AWAY}"])
        self.assertIs(state(self.home, f"card-{AWAY}.json")["sent"], True)


if __name__ == "__main__":
    unittest.main()
