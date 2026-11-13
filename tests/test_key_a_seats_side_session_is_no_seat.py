"""A session a seat started is that seat's and no seat, whatever runs in it.

A seat's tmux shim tags each session the seat starts with the seat's name, in the session's own
environment (`AK_TMUX_OWNER`).  One whose command took a model's turn ran a harness, and was
listed as a seat for as long as it ran: a row with no models, a card and a bar, gone with the
command.  ak's mark keeps a tagged session a seat, and a tag only the server's environment holds
tags no session.  Black-box, as tests/test_key_orch_list_skips.py is, which keeps that an untagged
session running a harness is listed.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from test_key_orch_list_skips import by_hand, harness, no_seat, rows

TAG = ("-e", "AK_TMUX_OWNER=acme")   # what the shim of seat acme gives a session it starts


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TaggedSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        by_hand(home, "acme-check", *TAG, *harness(home))
        by_hand(home, "acme-seat", *TAG, *harness(home), mark=True)
        cls.listed = home.ak("orch", "list")
        assert cls.listed.code == 0, cls.listed.err

    def test_a_tagged_session_running_a_harness_is_not_listed(self):
        self.assertEqual(rows(self.listed.out, "acme-check"), [])

    def test_asking_why_about_it_says_there_is_no_such_seat(self):
        done = self.home.ak("orch", "why", "acme-check")
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, no_seat("acme-check"))

    def test_with_aks_mark_it_is_a_seat(self):
        [row] = rows(self.listed.out, "acme-seat")
        self.assertRegex(row, r"\s\?\s+\?\s")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class UnreadableProcessTable(unittest.TestCase):
    def test_a_tagged_session_is_not_listed_where_ps_cannot_be_read(self):
        with Home() as home:
            home.fake("ps", "#!/bin/sh\nexit 1\n")
            by_hand(home, "acme-check", *TAG, *harness(home))
            by_hand(home, "scratch")   # listed: no table calls anything agentless
            done = home.ak("orch", "list")
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(rows(done.out, "acme-check"), [])
            self.assertEqual(len(rows(done.out, "scratch")), 1, done.out)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TagOnlyTheServerHolds(unittest.TestCase):
    def test_an_untagged_session_on_a_server_a_tagged_process_started_is_listed(self):
        with Home() as home:
            # the server takes the environment of the client that starts it, the tag with it
            done = home.run(REAL_TMUX, "-L", SOCKET, "-f", "/dev/null", "new-session", "-d",
                            "-s", "first", env={"AK_TMUX_OWNER": "acme"})
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(home.tmux("show-environment", "-g", "AK_TMUX_OWNER").out,
                             "AK_TMUX_OWNER=acme\n")
            by_hand(home, "notes", *harness(home))
            done = home.ak("orch", "list")
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(len(rows(done.out, "notes")), 1, done.out)


if __name__ == "__main__":
    unittest.main()
