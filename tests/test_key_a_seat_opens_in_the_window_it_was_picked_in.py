"""A seat picked in the menu opens in the terminal window it was picked in, whatever another did.

Two windows are two clients of the seats' tmux server.  The menu is opened in one by the real
`Ctrl-b m`, a key is typed in the other while it is up, and a seat is picked: tmux moves the
window the seat was picked in, and the other stays where it was.

Black-box: the program `AK_BIN` names, real clients on a Home's own tmux server, each a terminal
of its own, and the menu's popup drawn in it; judged by the session each client is in.  One seat
is opened by ak, a fake `claude` in it, which gives the server ak's `Ctrl-b m`.
"""

from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

CLAUDE = "#!/bin/sh\nexec sleep 600\n"


def until(test, what, bound=30):
    deadline = time.monotonic() + bound
    while not (found := test()):
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheWindowItWasPickedIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.seats = {name: Seat(home, name) for name in ("acme", "acme-two")}
        home.fake("claude", CLAUDE)
        done = home.ak("orch", "acme-three", "--model", "opus", "--workers", "opus", tty=True)
        assert done.code == 0, done.err

    def window(self, seat):
        """A person's terminal window on that seat, by tmux alone, and the name its client has."""
        terminal = Terminal(self.home, "-L", SOCKET, "attach-session", "-t", f"={seat}:",
                            program=REAL_TMUX)
        tty = self.home.tmux("display-message", "-p", "-t", terminal.pane, "#{pane_tty}",
                             server=SERVER).out.strip()
        # gone before the next test's window, which may be given the same tty
        self.addCleanup(until, lambda: tty not in self.where(), f"let {tty} go")
        self.addCleanup(self.home.tmux, "kill-session", "-t", terminal.pane, server=SERVER)
        until(lambda: self.where().get(tty) == seat, f"attached {tty} to {seat}")
        return terminal, tty

    def where(self):
        """Each client, by name: the seat it is in."""
        listed = self.home.tmux("list-clients", "-F", "#{client_tty}\t#{session_name}").out
        return dict(line.split("\t") for line in listed.splitlines())

    def pick(self, first, second, typed_in):
        """The menu opened in `first`, a key typed in `second`, and acme-three picked in it."""
        first.keys("C-b", "m")
        menu = first.wait("esc leave")
        number, = re.findall(r"(\d+)\s+acme-three\b", menu)
        before = self.seats[typed_in].typed()
        second.type("a")
        until(lambda: self.seats[typed_in].typed() != before, "took the key")
        first.type(number)
        until(lambda: "acme-three" in self.where().values(), "opened acme-three")

    def test_the_window_on_another_seat_stays_where_it_was(self):
        (first, mine), (second, theirs) = self.window("acme"), self.window("acme-two")
        self.pick(first, second, "acme-two")
        self.assertEqual(self.where(), {mine: "acme-three", theirs: "acme-two"})

    def test_the_other_window_on_the_same_seat_stays_too(self):
        (first, mine), (second, theirs) = self.window("acme"), self.window("acme")
        self.pick(first, second, "acme")
        self.assertEqual(self.where(), {mine: "acme-three", theirs: "acme"})


if __name__ == "__main__":
    unittest.main()
