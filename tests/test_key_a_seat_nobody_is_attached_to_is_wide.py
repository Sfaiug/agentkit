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
        self.assertEqual(
            self.home.tmux("show-options", "-wv", "-t", "=acme:", "window-size").out.strip(), "")

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
        self.assertEqual(
            self.home.tmux("show-options", "-wv", "-t", "=acme:", "window-size").out.strip(), "")
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

    def test_leaving_preserves_explicit_and_inherited_window_size_policies(self):
        self.home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
        for event in ("detach-client", "switch-client"):
            with self.subTest(event=event), Home() as home:
                home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
                open_seat(home, "acme")
                if event == "switch-client":
                    open_seat(home, "beta")
                target = "=acme:"
                self.assertEqual(
                    home.tmux("set-option", "-w", "-t", target, "window-size", "smallest").code, 0)
                term = Terminal(home, "-L", SOCKET, "attach-session", "-t", target,
                                size=(80, 26), program=REAL_TMUX)
                tty = home.tmux("display-message", "-p", "-t", term.pane, "#{pane_tty}",
                                server=SERVER).out.strip()
                until(lambda: size(home, "acme") == "80x24", "size acme to client")
                if event == "detach-client":
                    self.assertEqual(home.tmux("detach-client", "-t", tty).code, 0)
                    self.assertEqual(term.exit_code(), 0)
                else:
                    self.assertEqual(home.tmux("switch-client", "-c", tty, "-t", "=beta").code, 0)
                self.assertEqual(size(home, "acme"), "240x50")
                self.assertEqual(
                    home.tmux("show-options", "-wv", "-t", target, "window-size").out.strip(),
                    "smallest")

    def test_a_window_linked_into_another_attached_session_is_not_resized(self):
        self.home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
        open_seat(self.home, "acme")
        open_seat(self.home, "beta")
        self.assertEqual(self.home.tmux("new-session", "-d", "-s", "shell", "sleep 60").code, 0)
        self.assertEqual(self.home.tmux("link-window", "-s", "=shell:", "-t", "=acme:").code, 0)
        shell, shell_tty = self.attach("shell", 80, 26)
        until(lambda: self.home.tmux("display-message", "-p", "-t", "=shell:",
                                     "#{window_width}").out.strip() == "80",
              "size shell to its client")
        shared = self.home.tmux("display-message", "-p", "-t", "=shell:", "#{window_id}").out.strip()
        self.assertEqual(self.home.tmux(
            "set-hook", "-g", "window-resized",
            f"if-shell -F '#{{==:#{{hook_window}},{shared}}}' "
            "'set-option -g @acme_shared_resized yes'").code, 0)
        beta, beta_tty = self.attach("beta", 100, 32)
        self.assertEqual(self.home.tmux("detach-client", "-t", beta_tty).code, 0)
        self.assertEqual(beta.exit_code(), 0)
        self.assertEqual(self.home.tmux("show-options", "-gqv", "@acme_shared_resized").out.strip(), "")
        self.assertEqual(self.home.tmux("display-message", "-p", "-t", "=shell:",
                                        "#{window_width}").out.strip(), "80")
        self.assertEqual(self.home.tmux("detach-client", "-t", shell_tty).code, 0)
        self.assertEqual(shell.exit_code(), 0)

    def test_detaching_preserves_pane_splits_even_after_an_earlier_manual_resize(self):
        self.home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
        open_seat(self.home, "acme")
        target = "=acme:"
        self.assertEqual(self.home.tmux("resize-window", "-t", target, "-x", "60", "-y", "18").code, 0)
        self.assertEqual(self.home.tmux("set-option", "-wu", "-t", target, "window-size").code, 0)
        def widths():
            return tuple(map(int, self.home.tmux(
                "list-panes", "-t", target, "-F", "#{pane_width}").out.split()))
        first, tty = self.attach("acme", 120, 32)
        until(lambda: size(self.home, "acme") == "120x30", "size acme to first client")
        self.assertEqual(self.home.tmux("split-window", "-hd", "-l", "18", "-t", target,
                                        "sleep 60").code, 0)
        original = widths()
        self.assertEqual(original, (101, 18))
        self.assertEqual(self.home.tmux("detach-client", "-t", tty).code, 0)
        self.assertEqual(first.exit_code(), 0)
        self.assertEqual(size(self.home, "acme"), "240x50")
        second, tty = self.attach("acme", 120, 32)
        until(lambda: size(self.home, "acme") == "120x30", "size acme to second client")
        self.assertEqual(widths(), original)
        self.assertEqual(self.home.tmux("detach-client", "-t", tty).code, 0)
        self.assertEqual(second.exit_code(), 0)

    def test_an_unseen_aggressive_resize_window_returns_to_240_by_50(self):
        self.home.fake("claude", "#!/bin/sh\nexec sleep 60\n")
        open_seat(self.home, "acme")
        self.assertEqual(self.home.tmux("new-session", "-d", "-s", "shell", "sleep 60").code, 0)
        self.assertEqual(self.home.tmux("link-window", "-d", "-s", "=acme:", "-t", "=shell:").code, 0)
        self.assertEqual(self.home.tmux("set-option", "-w", "-t", "=acme:",
                                        "aggressive-resize", "on").code, 0)
        shell, shell_tty = self.attach("shell", 101, 32)
        claude, claude_tty = self.attach("acme", 80, 26)
        until(lambda: size(self.home, "acme") == "80x24", "size acme to its client")
        self.assertEqual(self.home.tmux("detach-client", "-t", claude_tty).code, 0)
        self.assertEqual(claude.exit_code(), 0)
        self.assertEqual(size(self.home, "acme"), "240x50")
        self.assertEqual(self.home.tmux("detach-client", "-t", shell_tty).code, 0)
        self.assertEqual(shell.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
