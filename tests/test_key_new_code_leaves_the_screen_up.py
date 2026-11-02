"""New code under an open menu starts it again with nothing between the two frames: the old
program's give comes under a hold (`?2026h`), and the new one's first frame, drawn from the read
handed over the exec, ends it (`?2026l`).  Leaving a seat after an install shows the list first.

Black-box: ak runs in a terminal of tests/fixtures/akterm.py over real seats.  tmux neither holds
nor passes mode 2026, so what the hold does is read from the program's own bytes, by `pipe-pane`;
what it leaves is read from tmux's modes and the terminal's attributes.
"""

import os
import re
import shlex
import sys
import termios
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEYS = "esc leave"
NAME = "atoll-fix"
HOLD, RELEASE = b"\x1b[?2026h", b"\x1b[?2026l"
ENTER, LEAVE = b"\x1b[?1049h", b"\x1b[?1049l"
# Every frame is an update of its own, ended as it is written; the hold is the one left open over
# a leave of the screen.
HELD = re.compile(rb"\x1b\[\?2026h(?:(?!\x1b\[\?2026l).)*?\x1b\[\?1049l", re.S)
ROW = NAME.encode()
MODES = "#{alternate_on} #{cursor_flag} #{mouse_any_flag} #{mouse_sgr_flag} #{keypad_flag}"


def until(test, what, bound=60):
    deadline = time.monotonic() + bound
    while (got := test()) is None or got is False:
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)
    return got


class Up(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        Seat(self.home, NAME, record={"created": int(time.time()) - 900})
        self.menu = self.opened()
        self.bytes = self.home.root / "program-bytes"
        done = self.home.tmux("pipe-pane", "-t", self.menu.pane,
                              f"cat >{shlex.quote(str(self.bytes))}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)

    def opened(self):
        menu = Terminal(self.home, size=(100, 30))
        menu.wait(KEYS, bound=60)
        self.drawn = time.time()               # it started before it drew
        return menu

    def said(self):
        return self.bytes.read_bytes() if self.bytes.exists() else b""

    def stamp(self):
        """An install: whole seconds, as install.sh stamps, past the second the menu started in."""
        while time.time() < int(self.drawn) + 1:
            time.sleep(0.05)
        self.home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")

    def restarted(self, since=0):
        """The bytes once a hold since `since` has ended: where its parts are in them."""
        def ended():
            said = self.said()
            held = HELD.search(said, since)
            return (said, held.start(), said.index(RELEASE, held.start())) \
                if held and RELEASE in said[held.start():] else None
        return until(ended, "held and let go")

    def modes(self, menu):
        """What the program left the terminal in: tmux's modes and its attributes."""
        shown = self.home.tmux("display-message", "-p", "-t", menu.pane, MODES, server=SERVER)
        tty = self.home.tmux("display-message", "-p", "-t", menu.pane, "#{pane_tty}",
                             server=SERVER).out.strip()
        fd = os.open(tty, os.O_RDONLY | os.O_NOCTTY)
        self.addCleanup(os.close, fd)
        return shown.out, termios.tcgetattr(fd)

    def test_the_hold_runs_from_before_the_give_to_after_the_first_frame(self):
        self.stamp()
        said, hold, release = self.restarted()
        left = said.index(LEAVE, hold)
        self.assertLess(said.index(ROW, said.index(ENTER, left)), release)

    def test_a_read_that_can_never_finish_holds_up_no_first_frame(self):
        run = self.home.path / ".agentkit/runs/fix-api/run.json"
        run.parent.mkdir(parents=True)
        os.mkfifo(run)
        self.addCleanup(run.unlink)
        self.stamp()
        said, hold, release = self.restarted()
        self.assertLess(said.index(ROW, said.index(ENTER, hold)), release)

    def test_leaving_a_seat_after_an_install_shows_the_list_before_the_hold(self):
        self.menu.keys("1")
        until(lambda: self.home.tmux("list-clients", "-F", "#{client_session}").out.split()
              == [NAME], "attached")
        self.menu.wait("❯")
        self.stamp()
        since = len(self.said())
        self.home.tmux("detach-client", "-s", f"={NAME}")
        said, hold, _ = self.restarted(since)
        entered = said.index(ENTER, since)
        self.assertLess(said.index(ROW, entered), hold)

    def test_esc_after_a_restart_leaves_the_terminal_as_a_menu_that_never_restarted(self):
        self.stamp()
        self.restarted()
        self.menu.wait(NAME)
        self.menu.keys("Escape")
        self.assertEqual(self.menu.exit_code(), 0)
        said = self.said()
        self.assertGreater(said.rindex(RELEASE), said.rindex(HOLD))
        never = self.opened()
        never.keys("Escape")
        self.assertEqual(never.exit_code(), 0)
        self.assertEqual(self.modes(self.menu), self.modes(never))


if __name__ == "__main__":
    unittest.main()
