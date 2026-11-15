"""A machine whose boot Linux cannot say gives ak no boot: a tick there ends well and reopens no
seat, as no reboot can be told from none, and the next tick that can read the boot reopens it.

A boot nobody can read is no stamp of the pair's clocks either, so it is never one boot taken
for another, nor `None` for a name.  Black-box: the program `AK_BIN` names runs `ak watch` from
outside through tests/fixtures/akbin.py, beside a seat tmux lost (tests/fixtures/akseat.py) whose
plan holds an open line; the first tick records a boot AK_NOW sets, the second runs where a file
no one may read stands over the kernel's boot id, the third on the host's own boot.  What came
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
BOOT_ID = "/proc/sys/kernel/random/boot_id"


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and bwrap")
class ABootLinuxCannotSay(unittest.TestCase):
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
        unread = home.write("unread-boot-id", "")
        unread.chmod(0)
        cls.ticks, cls.sessions = [], []
        for env, box in (({"AK_NOW": "1789000000 10000 acme-boot-1"}, ()),
                         (None, ("--bind", str(unread), BOOT_ID)), (None, ())):
            cls.ticks.append(home.tick(env=env, box=box))
            cls.sessions.append(cls.seats())

    @classmethod
    def seats(cls):
        listed = cls.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return sorted(set(listed) - {OWN})

    def test_every_tick_ends_well(self):
        for tick in self.ticks:
            self.assertEqual(tick.code, 0, tick.err)

    def test_a_tick_on_a_boot_linux_cannot_say_reopens_nothing(self):
        self.assertEqual(self.sessions[1], [])

    def test_the_next_tick_on_a_boot_it_can_say_reopens_the_seat_owing_work(self):
        self.assertEqual(self.sessions[2], ["acme"])


if __name__ == "__main__":
    unittest.main()
