"""A seat's tmux ends its own session and one that is no seat, and still owns its session after
a rename; a worker and a command of no seat type into any seat.

The guard that keeps a seat from ending or typing into another seat
(tests/test_key_tmux_shim_other_seat.py) must stop only that.  A seat closes the scratch sessions
it opens and, last, its own; `ak orch rename` leaves the seat's old name in its environment, and
under it the seat must still type into and end its session by the new name; ak's workers and the
owner's own commands drive any seat's pane.  A guard that refused these would break the seat's
own work.  Black-box: the shims a seat's launch installs (tests/fixtures/shims.py), run as a
seat's commands against the Home's real tmux, judged by the sessions tmux holds and what each
pane received; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

TYPES = ("ak refused `tmux send-keys`: it would type into beta, another session's seat. "
         "Nothing a seat writes is typed into another seat.\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhereTheGuardStandsAside(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        cls.beta = Seat(cls.home, "beta")

    def tmux(self, *args, seat, env=None):
        return self.shims.run("tmux", "-L", SOCKET, *args, seat=seat, env=env)

    def gone(self, name):
        return self.home.tmux("has-session", "-t", f"={name}").code != 0

    def test_a_seat_ends_its_own_session_and_a_scratch_session_it_opened(self):
        Seat(self.home, "gamma")
        for name in ("scratch", "gamma"):
            self.addCleanup(self.home.tmux, "kill-session", "-t", f"={name}")
        opened = self.tmux("new-session", "-d", "-s", "scratch", "sleep", "600", seat="gamma")
        self.assertEqual(opened.code, 0, opened.err)
        # its own session goes last: a seat's commands run inside it
        for name in ("scratch", "gamma"):
            with self.subTest(name=name):
                done = self.tmux("kill-session", "-t", name, seat="gamma")
                self.assertEqual(done.code, 0, done.err)
                self.assertTrue(self.gone(name))
        self.assertFalse(self.gone("beta"))

    def test_after_a_rename_its_old_name_types_into_and_ends_its_own_session(self):
        seat = Seat(self.home, "fix-api")
        self.addCleanup(self.home.tmux, "kill-session", "-t", "=fix-api2")
        renamed = self.home.ak("orch", "rename", "fix-api", "fix-api2")
        self.assertEqual(renamed.code, 0, renamed.err)
        count = len(seat.lines())
        for keys in (("-l", "hi"), ("Enter",)):
            done = self.tmux("send-keys", "-t", "=fix-api2:", *keys, seat="fix-api")
            self.assertEqual(done.code, 0, done.err)
        self.assertEqual(seat.wait_lines(count + 1)[count:], ["hi"])
        # still a seat to the guard: the old name owns only its own session
        refused = self.tmux("send-keys", "-t", "=beta:", "-l", "hi", seat="fix-api")
        self.assertEqual((refused.code, refused.err), (1, TYPES))
        done = self.tmux("kill-session", "-t", "fix-api2", seat="fix-api")
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(self.gone("fix-api2"))

    def test_a_worker_and_a_command_of_no_seat_type_into_another_seat(self):
        Seat(self.home, "acme")
        self.addCleanup(self.home.tmux, "kill-session", "-t", "=acme")
        for text, seat, env in (("x", "acme", {"AK_RUN_ROLE": "worker"}), ("y", None, None)):
            with self.subTest(seat=seat, env=env):
                count = len(self.beta.lines())
                for keys in (("-l", text), ("Enter",)):
                    done = self.tmux("send-keys", "-t", "=beta:", *keys, seat=seat, env=env)
                    self.assertEqual(done.code, 0, done.err)
                self.assertEqual(self.beta.wait_lines(count + 1)[count:], [text])


if __name__ == "__main__":
    unittest.main()
