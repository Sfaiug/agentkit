"""The boot a key sets in AK_NOW is the boot the whole of ak sees: a tick on another boot than the
tick before reopens a seat owing work, as after a reboot, and one on the same boot reopens none.

AK_NOW, a stamp's line (`wall seconds-since-boot boot`), sets both of a pair's clocks and the
boot for the one ak it is set for, so a standby's keys can step a clock or reboot one machine of
tests/fixtures/twohomes.py.  Here the host never reboots, and only the variable says it did.
Black-box: the program `AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py,
beside a seat tmux lost (tests/fixtures/akseat.py) whose plan holds an open line, and what came
back is the sessions on ak's tmux server; this test fails against `/bin/false`.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

OWN = "notes"   # the owner's own session on ak's tmux server, no seat

# Each tick's clocks and boot: the first only records its boot, as an install's first does; the
# second is ten minutes on, on that boot; the third on the boot after, a minute into it.
NOWS = ("1789000000 10000 acme-boot-1", "1789000600 10600 acme-boot-1",
        "1789001200 60 acme-boot-2")


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and bwrap")
class ABootAKeySets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        # The owner's own session keeps ak's tmux server up outside the box: a seat a tick
        # reopened is still there to see once the tick has ended.
        done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", OWN, "sleep 3600")
        assert done.code == 0, done.err
        Seat(home, "acme", alive=False, planned=True)
        cls.ticks, cls.sessions = [], []
        for now in NOWS:
            cls.ticks.append(home.tick(env={"AK_NOW": now}))
            cls.sessions.append(cls.seats())

    @classmethod
    def seats(cls):
        listed = cls.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return sorted(set(listed) - {OWN})

    def test_every_tick_ends_well(self):
        for tick in self.ticks:
            self.assertEqual(tick.code, 0, tick.err)

    def test_a_tick_on_the_boot_of_the_tick_before_reopens_nothing(self):
        self.assertEqual(self.sessions[1], [])

    def test_a_tick_on_another_boot_reopens_the_seat_owing_work(self):
        self.assertEqual(self.sessions[2], ["acme"])


if __name__ == "__main__":
    unittest.main()
