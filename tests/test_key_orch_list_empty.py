"""`ak orch list` with no seat anywhere says how to start one; any other word is a usage error.

It is what a person or a model runs first to see the seats, so with none it says how to open
one rather than print an empty table, and the slice line under it still says where agents run.
A listing only reads: it starts no tmux server and writes no state, and a person's own session
on their default tmux server is no seat and is left running.  Black-box: the program `AK_BIN`
names, run from outside through tests/fixtures/akbin.py and judged by what it prints and the
tmux servers it leaves; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home

EMPTY = ("no orchestrator session; `ak orch <name>` starts one\n"
         "no slice (no user systemd manager)\n")
USAGE = "ak orch: usage: ak orch list [--why]\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NoSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_with_no_seat_it_says_how_to_start_one_and_where_agents_run(self):
        for args in ((), ("--why",)):
            with self.subTest(args=args):
                done = self.home.ak("orch", "list", *args)
                self.assertEqual((done.code, done.out, done.err), (0, EMPTY, ""))

    def test_listing_starts_no_tmux_server_and_writes_no_state(self):
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        for server in (SOCKET, "default"):
            with self.subTest(server=server):
                self.assertNotEqual(self.home.tmux("list-sessions", server=server).code, 0)
        self.assertEqual(list((self.home.path / ".agentkit/state").iterdir()), [])

    def test_a_persons_own_session_on_their_default_server_is_no_seat_and_stays(self):
        with Home() as home:      # its own: the other cases have no server at all
            started = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "work",
                                "sleep 600", server="default")
            self.assertEqual(started.code, 0, started.err)
            done = home.ak("orch", "list")
            self.assertEqual((done.code, done.out), (0, EMPTY))
            self.assertEqual(home.tmux("has-session", "-t", "=work", server="default").code, 0)

    def test_any_other_argument_is_a_usage_error(self):
        for args in (("acme",), ("-x",), ("acme", "--why"), ("--why", "--why")):
            with self.subTest(args=args):
                done = self.home.ak("orch", "list", *args)
                self.assertEqual((done.code, done.out, done.err), (2, "", USAGE))


if __name__ == "__main__":
    unittest.main()
