"""A client runs no tick: `ak watch` on a machine whose server record (`state/server`, which
`install.sh --client` writes) names a home does none of a tick's work, says in one line whose
client the machine is, and exits 0.

A client's home may be a copy of its server's at the same paths, the standby's: its seats' records
and a watch.json whose boot id is the server's.  A tick there would resume every seat that owes
work on a second machine.  So the firing is decided before anything a tick reads or writes: it
leaves ~/.agentkit as it found it, the tick's log aside.  Without the record the same firing
resumes the seat.  The client's config.toml still holds a key by its old name, which any other
command renames, and its log is past the size a tick rolls it at, under a lock in the state
folder: the firing renames no key and leaves no lock.  Black-box: the program `AK_BIN` names
fires by cron's line, boxed, through tests/fixtures/akbin.py, its seat the record tmux lost
(tests/fixtures/akseat.py), and what it started is the sessions on ak's tmux server; this test
fails against `/bin/false`.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, REFUSED, Home, boxable
from fixtures.akseat import Seat

BOOT = Path("/proc/sys/kernel/random/boot_id").is_file()
SERVER = "acme-box"
LOG = ".agentkit/tmp/watch.log"
LOGS = (LOG, f"{LOG}.1")    # the tick's log, and the generation a roll of it keeps
OLD_LINE = "an earlier tick's line\n"
PAST_ITS_BOUND = 6 * 2**20      # bytes: past the 5 MiB a tick rolls its log at
OWN = "notes"   # the owner's own session on ak's tmux server, no seat


@unittest.skipUnless(REAL_TMUX and BOOT and boxable(), "needs tmux, a kernel boot id and bwrap")
class AClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"], settings={"rounds": 2})   # review_rounds' old name
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        # keeps ak's tmux server up outside the box, so a seat a tick resumed is still there
        done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", OWN, "sleep 3600")
        assert done.code == 0, done.err
        Seat(home, "acme", alive=False, planned=True)     # owes work, and tmux lost it
        home.write(".agentkit/state/watch.json", {"boot_id": "the server's"})
        home.write(LOG, OLD_LINE * (PAST_ITS_BOUND // len(OLD_LINE)))
        home.write(".agentkit/state/server", f"{SERVER}\n")
        cls.before = home.tree()
        cls.client = home.tick(cron=True)
        cls.client_sessions, cls.after = cls.sessions(), home.tree()
        # the firing's own lines: all the live log holds, unless it was not rolled
        cls.said = (home.path / LOG).read_text().removeprefix(
            cls.before[LOG].decode()).splitlines()
        cls.asked = {name: home.calls(name) for name in REFUSED}
        (home.path / ".agentkit/state/server").unlink()
        cls.server = home.tick(cron=True)
        cls.server_sessions = cls.sessions()

    @classmethod
    def sessions(cls):
        listed = cls.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return sorted(set(listed) - {OWN})

    def test_a_client_s_firing_resumes_starts_and_lands_nothing(self):
        self.assertEqual(self.client.code, 0, self.client.err)
        self.assertEqual(self.client_sessions, [])
        self.assertEqual({name: calls for name, calls in self.asked.items() if calls}, {})

    def test_it_says_in_one_line_whose_client_the_machine_is(self):
        self.assertEqual(len(self.said), 1, self.said)
        self.assertIn(f"client of {SERVER}", self.said[0])

    def test_it_leaves_the_home_as_it_was_the_log_aside(self):
        def home(tree):
            return {path: data for path, data in tree.items() if path not in LOGS}
        self.assertEqual(home(self.after), home(self.before))

    def test_without_the_record_the_same_firing_resumes_the_seat(self):
        self.assertEqual(self.server.code, 0, self.server.err)
        self.assertEqual(self.server_sessions, ["acme"])


if __name__ == "__main__":
    unittest.main()
