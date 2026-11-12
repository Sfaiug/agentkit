"""The answer key runs a seat's PATH shims as that seat's own commands.

A shim test holds only if tests/fixtures/shims.py has a seat's launch install the shims and runs
a command as a seat's shell would: its name found on the seat's PATH, the shim first and the
Home's own tool behind it, with the seat's name, a worker's role, or neither; and only if the
launch's server is gone by then, as a call that meets it on its way out fails.
"""

import os
import socket
import sys
from pathlib import Path
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

# The real rsync behind the shim says whose call it ran.
WHOSE = '#!/bin/sh\necho "${AGENTKIT_SESSION:-none} ${AK_RUN_ROLE:-none} $*"\n'


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Installed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)

    def test_the_launch_leaves_the_shims_and_no_seat_of_its_own(self):
        self.assertTrue((self.shims.dir / "tmux").is_file())
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=shimseat").code, 0)

    def test_a_command_finds_its_shim_and_the_homes_tool_behind_it(self):
        self.shims.fake("gh", code=4, out="answered")
        self.assertEqual(self.shims.run("gh", "pr", "view", "7", seat=None),
                         (4, "answered", ""))
        self.assertEqual(self.home.calls("gh"), [["pr", "view", "7"]])
        Seat(self.home, "acme")
        listed = self.shims.run("tmux", "-L", SOCKET, "list-sessions", "-F", "#S")
        self.assertEqual(listed, (0, "acme\n", ""))

    def test_a_command_runs_as_the_seat_a_worker_or_no_seat(self):
        self.home.fake("rsync", WHOSE)
        for seat, env, said in (("acme", None, "acme none a b\n"),
                                ("acme", {"AK_RUN_ROLE": "worker"}, "acme worker a b\n"),
                                (None, None, "none none a b\n")):
            with self.subTest(seat=seat, env=env):
                self.assertEqual(self.shims.run("rsync", "a", "b", seat=seat, env=env).out, said)

    def test_a_tool_with_no_shim_is_a_mistake_in_the_test(self):
        with self.assertRaises(AssertionError):
            self.shims.run("ls")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LaunchServer(unittest.TestCase):
    def test_no_call_after_meets_it_on_its_way_out(self):
        # Its last session stopped, the server exits, and a call that reaches it meanwhile fails
        # with `server exited unexpectedly`.  A client held a second past the stop keeps it up,
        # as a loaded host does: the shims are in only once nothing listens there.
        home = Home()
        self.addCleanup(home.close)
        path = str(home.tmux_dir / f"tmux-{os.getuid()}" / SOCKET)
        hold, ak = socket.socket(socket.AF_UNIX), home.ak
        self.addCleanup(hold.close)

        def stop(*args, **kwargs):
            if args[:2] != ("orch", "stop"):
                return ak(*args, **kwargs)
            hold.connect(path)
            done = ak(*args, **kwargs)
            threading.Timer(1, hold.close).start()
            return done

        home.ak = stop
        Shims(home)
        with socket.socket(socket.AF_UNIX) as call:
            self.assertRaises((ConnectionRefusedError, FileNotFoundError), call.connect, path)


if __name__ == "__main__":
    unittest.main()
