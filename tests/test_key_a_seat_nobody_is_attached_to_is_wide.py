"""A seat is 240 columns by 50 rows while nobody is attached to it, where tmux alone would leave
it 80 by 24: a line ak types then shows whole in its harness's input box, where ak reads it back
before it presses Enter (a box that shows half the pane's rows less five scrolls a draft taller
than that).  So is a seat opened on a server that was up before ak's config, and a seat whose last
client has detached or switched to another seat -- while an attached client still sizes the window
to itself, and the next client that attaches sizes it again.
Black-box: the program `AK_BIN` names opens the seats from outside (tests/fixtures/akbin.py),
judged by the size tmux gives their windows.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_a_seat_opens_in_the_window_it_was_picked_in import until
from test_key_tmux_conf import open_seat


def size(home, name):
    done = home.tmux("display-message", "-p", "-t", f"={name}:", "#{window_width}x#{window_height}")
    assert done.code == 0, done.err
    return done.out.strip()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatNobodyIsAttachedToIsWide(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def attach(self, name, width, height):
        term = Terminal(self.home, "-L", SOCKET, "attach-session", "-t", f"={name}:",
                        size=(width, height), program=REAL_TMUX)
        tty = self.home.tmux("display-message", "-p", "-t", term.pane, "#{pane_tty}",
                             server=SERVER).out.strip()
        until(lambda: f"{tty}\t{name}" in self.home.tmux(
            "list-clients", "-F", "#{client_tty}\t#{session_name}").out.splitlines(),
            f"attach {tty} to {name}")
        return term, tty

    def test_a_seat_ak_opens_is_240_by_50(self):
        open_seat(self.home, "acme")
        self.assertEqual(size(self.home, "acme"), "240x50")

    def test_so_is_one_opened_on_a_server_already_up(self):
        Seat(self.home, "acme")     # its server started on no config at all
        open_seat(self.home, "beta")
        self.assertEqual(size(self.home, "beta"), "240x50")

    def test_detaching_returns_a_seat_to_240_by_50_and_still_sizes_for_the_next_client(self):
        self.home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
        open_seat(self.home, "acme")
        first, _ = self.attach("acme", 80, 26)
        until(lambda: size(self.home, "acme") == "80x24", "size to the first client")
        done = self.home.tmux("detach-client", "-s", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(first.exit_code(), 0)
        self.assertEqual(size(self.home, "acme"), "240x50")

        second, _ = self.attach("acme", 90, 30)
        until(lambda: size(self.home, "acme") == "90x28", "size to the next client")
        done = self.home.tmux("detach-client", "-s", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(second.exit_code(), 0)
        self.assertEqual(size(self.home, "acme"), "240x50")

    def test_switching_away_restores_a_left_seat_while_another_client_keeps_its_size(self):
        self.home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
        open_seat(self.home, "acme")
        open_seat(self.home, "beta")
        first, _ = self.attach("acme", 80, 26)
        until(lambda: size(self.home, "acme") == "80x24", "size acme to first client")
        second, second_tty = self.attach("acme", 100, 32)
        until(lambda: size(self.home, "acme") == "100x30", "size acme to second client")

        done = self.home.tmux("switch-client", "-c", second_tty, "-t", "=beta")
        self.assertEqual(done.code, 0, done.err)
        until(lambda: size(self.home, "beta") == "100x30", "size beta to second client")
        until(lambda: size(self.home, "acme") == "80x24", "keep acme at first client size")

        done = self.home.tmux("detach-client", "-s", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(first.exit_code(), 0)
        self.assertEqual(size(self.home, "acme"), "240x50")
        self.assertEqual(size(self.home, "beta"), "100x30")

        done = self.home.tmux("switch-client", "-c", second_tty, "-t", "=acme")
        self.assertEqual(done.code, 0, done.err)
        until(lambda: size(self.home, "acme") == "100x30", "size acme back to second client")
        self.assertEqual(size(self.home, "beta"), "240x50")

        done = self.home.tmux("detach-client", "-s", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(second.exit_code(), 0)
        self.assertEqual(size(self.home, "acme"), "240x50")
        self.assertEqual(size(self.home, "beta"), "240x50")


if __name__ == "__main__":
    unittest.main()
