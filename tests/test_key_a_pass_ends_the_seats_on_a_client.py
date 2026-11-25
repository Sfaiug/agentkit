"""`ak standby ALIAS`, run on a client of ALIAS, ends the session of ak's tmux server there that
`orch.start` marked as a seat, and leaves a session beside it that has no mark of its own, though
every session inherits one; the pass exits 0.  Black-box, through tests/fixtures/twohomes.py, the
seat tests/fixtures/akseat.py's: what came back is the pass's exit and the sessions ak's tmux
server holds on the client.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, boxable
from fixtures.akseat import Seat
from fixtures.twohomes import Machines


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and a bwrap able to build a machine here")
class APassOnAClient(unittest.TestCase):
    def test_it_ends_the_seat_and_leaves_the_session_with_no_mark_of_its_own(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            Seat(home, "fix-api", alive=False, planned=True)    # the record a pass copies
            Seat(here, "fix-api", planned=True)
            here.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 3600")
            here.tmux("set-option", "-g", "@ak_orch", "1")
            done = here.ak("standby", home.name)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(here.tmux("list-sessions", "-F", "#{session_name}").out.split(),
                             ["notes"])


if __name__ == "__main__":
    unittest.main()
