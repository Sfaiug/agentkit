"""ak's seats live on the tmux server its socket setting names, and the default server is a
person's own.

Seats are on `tmux -L agentkit`, or the server AGENTKIT_TMUX_SOCKET names, so nothing ak does
reaches another tmux user's sessions and a test reaches none of the owner's.  The default server
is read only for the marked seats of old, listed as `legacy`: listing, the menu and a tick leave
it, and any server the setting does not name, exactly as they found it; stopping a legacy seat
ends that one session where it is.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, and every server is one of the Home's own.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home

# server: {session: marked as ak's seat}
SERVERS = {SOCKET: {"acme": True}, "akmap-test": {"beta": True},
           "agentkit": {"gamma": True},
           "default": {"old-seat": True, "mine": False}}
NAMES = {name for sessions in SERVERS.values() for name in sessions}


def open_session(home, server, name, marked):
    done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", name, "-x", "80", "-y", "24",
                     "sleep 600", server=server)
    assert done.code == 0, done.err
    if marked:
        done = home.tmux("set-option", "-t", f"={name}:", "@ak_orch", "1", server=server)
        assert done.code == 0, done.err


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TmuxSocketSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        for server, sessions in SERVERS.items():
            for name, marked in sessions.items():
                open_session(cls.home, server, name, marked)

    def listed(self, env=None):
        """Each of this test's sessions the listing shows, with the words of its row.  A row
        that does not fit the width goes on indented lines under the seat's name."""
        done = self.home.ak("orch", "list", env=env)
        self.assertEqual(done.code, 0, done.err)
        rows, name = {}, None
        for line in done.out.splitlines()[1:]:
            if line[:1].strip():
                name = line.split()[0]
                rows[name] = []
            if name:
                rows[name] += line.split()
        return {name: words for name, words in rows.items() if name in NAMES}

    def snapshot(self, server):
        """Everything ak could change on a server: its sessions, their options and screens."""
        ask = self.home.tmux
        shot = [ask("list-sessions", "-F", "#{session_name} #{session_windows}",
                    server=server).out]
        for scope in ("-g", "-s"):
            shot.append(ask("show-options", scope, server=server).out)
        shot.append(ask("show-window-options", "-g", server=server).out)
        for name in SERVERS[server]:
            for question in (("show-options", "-t", f"={name}:"),
                             ("show-window-options", "-t", f"={name}:"),
                             ("list-panes", "-F", "#{pane_id} #{pane_dead}", "-t", f"={name}:"),
                             ("capture-pane", "-p", "-t", f"={name}:")):
                shot.append(ask(*question, server=server))
        return shot

    def test_seats_are_listed_from_the_server_the_socket_setting_names(self):
        self.assertEqual(set(self.listed()), {"acme", "old-seat"})
        self.assertEqual(set(self.listed({"AGENTKIT_TMUX_SOCKET": "akmap-test"})),
                         {"beta", "old-seat"})

    def test_without_a_socket_setting_seats_are_on_the_agentkit_server(self):
        for unset in (None, ""):
            with self.subTest(setting=unset):
                self.assertEqual(set(self.listed({"AGENTKIT_TMUX_SOCKET": unset})),
                                 {"gamma", "old-seat"})

    def test_only_a_marked_session_on_the_default_server_is_listed_and_as_legacy(self):
        rows = self.listed()
        self.assertNotIn("mine", rows)
        self.assertEqual(rows["old-seat"][-1], "legacy")
        self.assertNotIn("legacy", rows["acme"])

    def test_listing_the_menu_and_a_tick_leave_every_other_server_as_it_was(self):
        others = ("default", "agentkit", "akmap-test")
        before = {server: self.snapshot(server) for server in others}
        for args in (("orch", "list"), ("--dry-run",), ("watch",)):
            done = self.home.ak(*args)
            self.assertEqual(done.code, 0, f"ak {' '.join(args)}: {done.err}")
        for server in others:
            with self.subTest(server=server):
                self.assertEqual(self.snapshot(server), before[server])

    def test_stopping_a_legacy_seat_ends_it_on_the_default_server_and_nothing_beside_it(self):
        open_session(self.home, "default", "fix-api", True)
        done = self.home.ak("orch", "stop", "fix-api")
        self.assertEqual(done.code, 0, done.err)
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=fix-api",
                                           server="default").code, 0)
        for name in ("old-seat", "mine"):
            self.assertEqual(self.home.tmux("has-session", "-t", f"={name}",
                                            server="default").code, 0, name)


if __name__ == "__main__":
    unittest.main()
