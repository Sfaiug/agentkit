"""A standby that takes over from its home reopens the seats its copy says owe work: while it is a
client, its passes copy the home's seat records and watch state (whose boot id is the home's, not
this machine's), and neither its tick nor its pass opens a seat on ak's tmux server there; once it
takes over (the lease is its own and its pass runs `install.sh --server`), the first firing of its
tick as home reopens the seat, as a tick on another boot than the tick before reopens a seat owing
work (tests/test_key_boot_a_key_can_set.py).

Black-box: the program `AK_BIN` names runs on the pair of tests/fixtures/twohomes.py, built and
fired as tests/test_key_standby_becomes_home.py builds and fires it, with a seat tmux lost whose
plan holds an open line (tests/fixtures/akseat.py, as tests/test_key_client_runs_no_tick.py makes
one).  What came back is each pass's and tick's exit, the takeover's record of a server and
crontab, and the sessions ak's tmux server holds on the standby, read after each step.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, SOCKET, boxable
from fixtures.akseat import Seat
import test_key_standby_becomes_home as becoming
from test_key_standby_watches_its_homes_lease import now

SEAT = "acme"


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and a bwrap able to build a machine here")
class ATakeoverReopensItsSeats(unittest.TestCase):
    # the machines, their passes and the lease the standby takes, the key of a standby becoming
    # home's own: its class reached through its module, so this file runs none of its cases
    own = becoming.AStandbyBecomesHome
    fire, lease, passes, kept, notes = own.fire, own.lease, own.passes, own.kept, own.notes
    becomes_home = own.becomes_home

    def setUp(self):
        self.own.setUp(self)
        akconfig.write(self.home, ["opus"])
        # a collection on record from just now: one due would outlive a tick's box
        self.home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        # cwd on the machine's own path, where both home and standby find ~/code/<seat>
        Seat(self.home, SEAT, alive=False, planned=True,
             record={"cwd": f"{self.home.env['HOME']}/code/{SEAT}"})
        # ak's tmux server up in the standby's machine outside any tick's pid box, holding no
        # session, so a seat a tick opens stays there to read once the tick has ended
        started = self.standby.run("tmux", "-L", SOCKET, "-f", "/dev/null",
                                   "start-server", ";", "set-option", "-s", "exit-empty", "off")
        self.assertEqual(started.code, 0, started.err)

    def sessions(self):
        """The sessions ak's tmux server holds on the standby now, by name."""
        listed = self.standby.tmux("list-sessions", "-F", "#{session_name}")
        self.assertEqual(listed.code, 0, listed.err)
        return sorted(listed.out.removesuffix("\n").split("\n")) if listed.out else []

    def test_a_takeover_reopens_the_seat_its_copy_holds(self):
        # 1. home holds the owing seat's record and its tick records its boot; a pass copies both
        self.read.add(self.fire(0))
        self.assertEqual(self.passes(1), 0)
        self.assertEqual(self.sessions(), [])
        # 2. still a client: its pass (swapping the lease) and its tick open no session
        self.assertEqual(self.passes(21), 0)
        self.assertEqual(self.sessions(), [])
        self.standby.env["AK_NOW"] = now(22)
        client_tick = self.standby.tick(raw=True)
        self.assertEqual(client_tick.code, 0, client_tick.err)
        self.assertEqual(self.sessions(), [])
        # 3. takeover: finding its own lease, the pass runs install.sh --server and copies nothing
        before = self.kept()
        self.assertEqual(self.notes(), b"notes\n")
        self.home.write(becoming.NOTES, "changed\n")
        self.becomes_home(24, before)
        self.assertEqual(self.sessions(), [])
        # 4. first firing of its tick as home reopens the seat from the copied records
        self.standby.env["AK_NOW"] = now(27)
        home_tick = self.standby.tick(raw=True)
        self.assertEqual(home_tick.code, 0, home_tick.err)
        self.assertEqual(self.sessions(), [SEAT])


if __name__ == "__main__":
    unittest.main()
