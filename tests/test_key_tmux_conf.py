"""Seats run under ak's own tmux config, ~/.agentkit/state/tmux.conf, and never the owner's.

The owner's ~/.tmux.conf is theirs: ak neither reads nor writes it.  What a seat needs from the
server is ak's file: the mouse on, so a touch scroll on a phone scrolls the output instead of
sending arrow keys to the harness; 50000 lines of history to scroll; panes kept when their
program exits, so a harness that quits as it opens leaves its seat; passthrough on; and
`Ctrl-b m`, the menu over whatever is running.  A server ak starts runs on that file, and one
already up when a seat opens is given it too.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

CONF = ".agentkit/state/tmux.conf"
SETTINGS = {"mouse": "on", "history-limit": "50000", "remain-on-exit": "on",
            "allow-passthrough": "on"}
# Each file a tmux started without -f would read, with a mark of the owner's in it.
OWNERS = {".tmux.conf": "set -g @acme-home yes\nset -g history-limit 1234\n",
          ".config/tmux/tmux.conf": "set -g @acme-xdg yes\n"}


def open_seat(home, name):
    cwd = home.path / "code" / name
    cwd.mkdir(parents=True, exist_ok=True)
    done = home.ak("orch", name, "--model", "opus", "--workers", "opus", tty=True, cwd=cwd)
    assert done.code == 0, done.err
    return done


class OnTmux(unittest.TestCase):
    def option(self, name):
        done = self.home.tmux("show-options", "-gqv", name)
        self.assertEqual(done.code, 0, done.err)
        return done.out.strip()

    def assertServerOnAksConfig(self):
        for name, value in SETTINGS.items():
            with self.subTest(option=name):
                self.assertEqual(self.option(name), value)
        done = self.home.tmux("list-keys", "-T", "prefix", "m")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("attach --overlay", done.out)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AServerAkStarts(OnTmux):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        for relative, text in OWNERS.items():
            cls.home.write(relative, text)
        open_seat(cls.home, "acme")

    def test_ak_writes_its_own_config_with_the_seat_settings_and_the_menu_key(self):
        lines = (self.home.path / CONF).read_text().splitlines()
        for name, value in SETTINGS.items():
            self.assertIn(f"set -g {name} {value}", lines)
        menu = [line for line in lines if line.startswith("bind-key m ")]
        self.assertEqual(len(menu), 1, lines)
        self.assertIn("attach --overlay", menu[0])

    def test_the_server_it_starts_runs_on_that_config(self):
        self.assertEqual(self.home.tmux("has-session", "-t", "=acme").code, 0)
        self.assertServerOnAksConfig()

    def test_the_owners_tmux_config_is_neither_read_nor_written(self):
        for relative, text in OWNERS.items():
            with self.subTest(file=relative):
                self.assertEqual((self.home.path / relative).read_text(), text)
        for mark in ("@acme-home", "@acme-xdg"):
            with self.subTest(mark=mark):
                self.assertEqual(self.option(mark), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AServerAlreadyUp(OnTmux):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        Seat(cls.home, "acme")      # its server started on no config at all
        cls.before = cls.home.tmux("show-options", "-gqv", "mouse").out.strip()
        open_seat(cls.home, "beta")

    def test_opening_a_seat_on_it_gives_it_aks_config(self):
        self.assertEqual(self.before, "off")
        self.assertEqual(self.home.tmux("has-session", "-t", "=beta").code, 0)
        self.assertServerOnAksConfig()

    def test_no_tmux_config_of_the_owners_is_made(self):
        for relative in OWNERS:
            with self.subTest(file=relative):
                self.assertFalse((self.home.path / relative).exists())


if __name__ == "__main__":
    unittest.main()
