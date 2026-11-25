"""A standby's pass ends the sessions marked as seats on ak's tmux server: `ak standby ALIAS`, on
ALIAS's client, ends a seat open there and leaves an unmarked session of the same server; then,
the record of a server removed, a tick's firing resumes that seat.  Black-box: the program
`AK_BIN` names runs from outside (tests/fixtures/akbin.py, its seat tests/fixtures/akseat.py's),
and what came back is the sessions on ak's tmux server; this test fails against `/bin/false`.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

BOOT = Path("/proc/sys/kernel/random/boot_id").is_file()


@unittest.skipUnless(REAL_TMUX and BOOT and boxable(), "needs tmux, a kernel boot id and bwrap")
class APassOnAClient(unittest.TestCase):
    def test_it_ends_the_seat_leaves_the_unmarked_session_and_a_home_resumes_the_seat(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            # a collection on record from just now: one due would outlive the tick's box
            home.write(".agentkit/state/gc.json", {"started_at": time.time()})
            home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 3600")
            Seat(home, "fix-api", planned=True)
            home.write(".agentkit/state/watch.json", {"boot_id": "the home's"})
            home.write(".agentkit/state/server", "acme-box\n")
            sessions = lambda: home.tmux("list-sessions", "-F", "#{session_name}").out.split()
            home.ak("standby", "acme-box")
            self.assertEqual(sessions(), ["notes"])
            (home.path / ".agentkit/state/server").unlink()
            self.assertEqual(home.tick(cron=True).code, 0)
            self.assertEqual(sorted(sessions()), ["fix-api", "notes"])


if __name__ == "__main__":
    unittest.main()
