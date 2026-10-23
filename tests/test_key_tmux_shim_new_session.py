"""Inside a seat, what its tmux starts speaks for the seat, and a session it makes names its maker.

tmux starts a pane's process in its server's environment, not the caller's, so an `ak run` a
seat started in a tmux session or window of its own would otherwise know no seat: its work
reviewed as someone else's, its ending told to no one.  A seat's tmux gives each process a call
starts the seat's name (`AGENTKIT_SESSION`), by the name the seat goes by now, and each session
it makes also names the seat that made it (`AK_TMUX_OWNER` in the session's environment, where
ak's tick reads it before closing a seat's finished sessions); a window added to a session
makes it no one's, and a worker's call and one of no seat add nothing.  Black-box: the shims a
seat's launch installs (tests/fixtures/shims.py), run as a seat's commands against the Home's
real tmux, judged by what each started process saw and what tmux keeps in the session's
environment; this test fails against `/bin/false`.
"""

import itertools
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

# The process tmux starts writes the seat name it was started with, then stays, as a harness does.
PROBE = 'printf "%s\\n" "${AGENTKIT_SESSION-unset}" >"$0"; exec sleep 600'
NUMBERS = itertools.count()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatStarts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        Seat(cls.home, "acme")
        # The server's own environment names no seat: a process sees one only if its call gave it.
        cls.home.tmux("set-environment", "-g", "-u", "AGENTKIT_SESSION")
        # A session no seat made and ak keeps no record of, to start windows and panes in.
        done = cls.home.tmux("new-session", "-d", "-s", "plain", "-P", "-F", "#{pane_id}",
                             "sleep 600")
        assert done.code == 0, done.err
        cls.plain_pane = done.out.strip()

    def tmux(self, *args, seat="acme", env=None):
        done = self.shims.run("tmux", "-L", SOCKET, *args, seat=seat, env=env)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def probe(self):
        """A command for tmux to start, and the file it writes the seat name it saw to."""
        out = self.home.root / f"probe-{next(NUMBERS)}"
        return ["sh", "-c", PROBE, str(out)], out

    def saw(self, out, bound=30):
        """The seat name a started process saw, once it has written it."""
        deadline = time.monotonic() + bound
        while not (out.exists() and out.read_text().endswith("\n")):
            if time.monotonic() > deadline:
                raise AssertionError(f"no process tmux started wrote {out}")
            time.sleep(0.05)
        return out.read_text().strip()

    def owner(self, session):
        """The seat a session's own environment names as its maker, or None."""
        done = self.home.tmux("show-environment", "-t", f"={session}", "AK_TMUX_OWNER")
        return done.out.strip().removeprefix("AK_TMUX_OWNER=") if done.code == 0 else None

    def session(self, *args, seat="acme", env=None):
        """Make a session through the seat's tmux; (its name, the seat its process saw)."""
        command, out = self.probe()
        printed = self.tmux(*args, "-P", "-F", "#{session_name}", *command, seat=seat, env=env)
        name = printed.strip()
        self.addCleanup(self.home.tmux, "kill-session", "-t", f"={name}")
        return name, self.saw(out)

    def test_a_session_a_seat_makes_names_the_seat_to_its_process_and_as_its_owner(self):
        for args in (("new-session", "-d", "-s", "scratch"), ("new", "-d", "-s", "scratch2"),
                     ("new-session", "-d")):          # unnamed: tmux names it
            with self.subTest(args=args):
                name, saw = self.session(*args)
                self.assertEqual((saw, self.owner(name)), ("acme", "acme"))

    def test_each_window_and_pane_a_seat_starts_carries_its_name(self):
        for args in (("new-window", "-d", "-t", "=plain:"), ("neww", "-d", "-t", "=plain:"),
                     ("split-window", "-d", "-t", "=plain:"), ("splitw", "-d", "-t", "=plain:"),
                     ("respawn-pane", "-k", "-t", self.plain_pane)):
            with self.subTest(args=args):
                command, out = self.probe()
                self.tmux(*args, *command)
                self.assertEqual(self.saw(out), "acme")
        # a window in a session it did not make does not make the session its
        self.assertIsNone(self.owner("plain"))

    def test_each_command_of_a_chained_call_carries_it(self):
        first, first_out = self.probe()
        second, second_out = self.probe()
        self.addCleanup(self.home.tmux, "kill-session", "-t", "=chain")
        self.tmux("new-session", "-d", "-s", "chain", *first, ";",
                  "split-window", "-d", "-t", "=chain:", *second)
        self.assertEqual((self.saw(first_out), self.saw(second_out)), ("acme", "acme"))
        self.assertEqual(self.owner("chain"), "acme")

    def test_a_renamed_seat_gives_the_name_it_goes_by_now(self):
        # what `ak orch rename` leaves at the old name; the seat's processes still carry it
        self.home.write(".agentkit/state/session-old.json", {"renamed": "acme"})
        name, saw = self.session("new-session", "-d", "-s", "renamed", seat="old")
        self.assertEqual((saw, self.owner(name)), ("acme", "acme"))

    def test_a_name_the_seat_gives_its_process_itself_wins(self):
        name, saw = self.session("new-session", "-d", "-s", "named",
                                 "-e", "AGENTKIT_SESSION=beta")
        self.assertEqual((saw, self.owner(name)), ("beta", "acme"))

    def test_a_worker_and_a_command_of_no_seat_add_nothing(self):
        for name, seat, env in (("worker", "acme", {"AK_RUN_ROLE": "worker"}),
                                ("seatless", None, None)):
            with self.subTest(name):
                made, saw = self.session("new-session", "-d", "-s", name, seat=seat, env=env)
                self.assertEqual((saw, self.owner(made)), ("unset", None))
                command, out = self.probe()
                self.tmux("new-window", "-d", "-t", "=plain:", *command, seat=seat, env=env)
                self.assertEqual(self.saw(out), "unset")


if __name__ == "__main__":
    unittest.main()
