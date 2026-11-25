"""`ak orch NAME` on a client opens no seat: on a machine whose server record (`state/server`,
which `install.sh --client` writes) names a home, for a seat tmux lost, it exits non-zero, names
the home, and ak's tmux server holds no session.  With the record removed the same command opens
the seat.

A client's seats are on its home, and a standby's ~/.agentkit is a copy of that home's, seat
records among them: on 22 Nov 2026 a standby opened all 21 of its home's sessions a second time.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, the seat
is only its record (tests/fixtures/akseat.py), and what opened is the sessions on ak's tmux server.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

SERVER = "acme-box"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClient(unittest.TestCase):
    def test_a_client_refuses_the_seat_naming_its_home_and_a_home_opens_it(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            Seat(home, "acme", alive=False)     # tmux lost it
            record = home.write(".agentkit/state/server", f"{SERVER}\n")
            sessions = lambda: home.tmux("list-sessions", "-F", "#{session_name}").out.split()
            refused = home.ak("orch", "acme")
            self.assertNotEqual(refused.code, 0, refused.out)
            self.assertIn(SERVER, refused.out + refused.err)
            self.assertEqual(sessions(), [])
            record.unlink()
            opened = home.ak("orch", "acme")
            self.assertEqual(opened.code, 0, opened.out + opened.err)
            self.assertEqual(sessions(), ["acme"])


if __name__ == "__main__":
    unittest.main()
