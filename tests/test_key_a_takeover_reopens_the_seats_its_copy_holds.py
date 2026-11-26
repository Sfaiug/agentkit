"""A takeover still reopens the seats its copy holds that owe work.  While a standby is its home's
client, with the record of such a seat in the copy its passes made, a firing of its tick leaves
ak's tmux server there with no session of the seat.  Once the pass that finds the lease its own
has made the machine a home, the next firing opens the seat there, as a tick on another boot than
the tick before reopens a seat owing work (tests/test_key_boot_a_key_can_set.py): the tick
before, by the copy, was the home's.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, a home,
acme-mini, and its standby, acme-vm, built and fired as tests/test_key_standby_becomes_home.py
builds and fires them, through the pass that makes the standby a home, each machine's clock and
boot from AK_NOW.  The seat is the record tmux lost (tests/fixtures/akseat.py), its plan holding
an open line and its folder named by the path the machines have it at.  What opened is the
sessions on ak's tmux server on the standby, the owner's own aside.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, boxable
from fixtures.akseat import Seat
import test_key_standby_becomes_home as becoming
from test_key_standby_watches_its_homes_lease import now

OWN = "notes"   # the owner's own session on ak's tmux server, no seat


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and a bwrap able to build a machine here")
class ATakeover(unittest.TestCase):
    def setUp(self):
        # the machines and the standby's passes, the becoming key's own
        self.case = becoming.AStandbyBecomesHome()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def fires(self, minute):
        """The standby's tick at `minute`, which exits 0: the sessions on ak's tmux server there
        after it, the owner's own aside."""
        standby = self.case.standby
        standby.env["AK_NOW"] = now(minute)
        fired = standby.tick()
        self.assertEqual(fired.code, 0, fired.out + fired.err)
        listed = standby.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return sorted(set(listed) - {OWN})

    def test_a_client_opens_none_and_once_it_is_home_its_tick_opens_the_seat(self):
        case = self.case
        # owes work, and tmux lost it; its folder as a machine names it, not this side
        Seat(case.home, "fix-api", alive=False, planned=True,
             record={"cwd": f"{case.home.env['HOME']}/code/fix-api"})
        # The owner's own session keeps ak's tmux server up outside a tick's box, so a seat a tick
        # opened is still there once the tick has ended: started by a command on the machine, as
        # a server reads ak's tmux config and starts a seat's harness where it runs.
        own = case.standby.run("tmux", "-L", SOCKET, "-f", "/dev/null", "new-session", "-d",
                               "-s", OWN, "sleep 3600")
        self.assertEqual(own.code, 0, own.err)
        before = case.took()        # a client still, the seat's record in its copy
        self.assertEqual(self.fires(22), [])
        case.becomes_home(24, before)
        self.assertEqual(self.fires(27), ["fix-api"])


if __name__ == "__main__":
    unittest.main()
