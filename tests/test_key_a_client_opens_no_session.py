"""A client opens no session: on a machine whose server record (`state/server`, which
`install.sh --client` writes) names a home, `ak orch NAME` for a seat tmux lost, from a pipe or
typed at a terminal, exits non-zero, names the home, and ak's tmux server holds no session it did
not hold.  So does `ak orch` typed at a terminal with a model and a worker, for a new seat by
that name or by none yet.  Each leaves HOME as it found it.  With the record removed
`ak orch NAME` opens the seat.

A client's seats are on its home, and a standby's ~/.agentkit is a copy of that home's, seat
records among them: on 22 Nov 2026 a standby opened all 21 of its home's sessions a second time.
What a standby takes over with is that copy: a new seat refused only at its start had replaced
the seat's record by then, and removed its plan and pictures; and a request refused after the
records were read through their harnesses had dropped, from another seat's, a conversation no
launch of ak's handed out.  The copy's watch.json holds the home's boot too, from which the
machine that takes over resumes each seat owing work: the menu's popup (`ak attach --overlay`) on
a client opens no session and leaves that boot's recovery, so with the record removed the next
one resumes the seat.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, a seat
is only its record (tests/fixtures/akseat.py), and what opened is the sessions on ak's tmux server.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

BOOT = Path("/proc/sys/kernel/random/boot_id").is_file()
SERVER = "acme-box"
NEW = ("--model", "opus", "--workers", "opus")      # what asks `ak orch` for a new seat


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClient(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        Seat(home, "acme", alive=False, planned=True)     # owes work, and tmux lost it
        home.write(".agentkit/state/pictures-acme.jsonl", '{"picture": "acme"}\n')
        home.write(".agentkit/state/watch.json", {"boot_id": "the server's"})
        self.record = home.write(".agentkit/state/server", f"{SERVER}\n")

    def sessions(self):
        return self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()

    def assertRefused(self, done, before):
        self.assertNotEqual(done.code, 0, done.out)
        self.assertIn(SERVER, done.out + done.err)
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.home.tree(), before)

    def test_it_refuses_the_seat_and_a_new_one_and_a_home_opens_the_seat(self):
        home = self.home
        # its conversation no launch handed out: a harness reconciling its record drops it
        Seat(home, "fix-api", alive=False, record={"id_source": "legacy"})
        before = home.tree()
        refused = home.ak("orch", "acme")
        self.assertRefused(refused, before)
        for new in ((), NEW):       # typed at a terminal: the seat, then a new one by its name
            self.assertRefused(home.ak("orch", "acme", *new, tty=True), before)
        self.assertRefused(home.ak("orch", *NEW, tty=True, input="ship-docs\n"), before)
        self.record.unlink()
        opened = home.ak("orch", "acme")
        self.assertEqual(opened.code, 0, opened.out + opened.err)
        self.assertEqual(self.sessions(), ["acme"])

    @unittest.skipUnless(BOOT, "no kernel boot id")
    def test_its_popup_leaves_the_boot_s_recovery_to_the_machine_that_takes_over(self):
        client = self.home.ak("attach", "--overlay")
        self.assertEqual((client.code, self.sessions()), (0, []), client.err)
        self.record.unlink()        # as `install.sh --server` does where a standby takes over
        home = self.home.ak("attach", "--overlay")
        self.assertEqual((home.code, self.sessions()), (0, ["acme"]), home.err)


if __name__ == "__main__":
    unittest.main()
