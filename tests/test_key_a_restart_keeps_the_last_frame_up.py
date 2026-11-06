"""A restart on new code keeps the old frame up however long the new program's read takes: its
rows cross the exec, and the new program writes them as it takes the terminal, ending the hold
(`?2026l`) before its first frame.  Once, and only on a terminal of the size they were laid out for.

Black-box: ak runs in a terminal of tests/fixtures/akterm.py over a real seat.  tmux neither holds
nor passes mode 2026, so all this is read from the program's own bytes, by `pipe-pane`.
"""

import fcntl
import os
from pathlib import Path
import re
import shlex
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import KEEP, SERVER, Terminal

KEYS = "esc leave"
NAME = "atoll-fix"
ROW = NAME.encode()
BAR = "━".encode()
HOLD, RELEASE = b"\x1b[?2026h", b"\x1b[?2026l"
ENTER, LEAVE = b"\x1b[?1049h", b"\x1b[?1049l"
UPDATE = re.compile(rb"\x1b\[\?2026[hl]")
HELD = re.compile(rb"\x1b\[\?2026h(?:(?!\x1b\[\?2026l).)*?\x1b\[\?1049l", re.S)


def until(test, what, bound=60):
    deadline = time.monotonic() + bound
    while (got := test()) is None or got is False:
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.02)
    return got


def stopped(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "T"


class Restart(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        Seat(self.home, NAME, record={"created": int(time.time()) - 900})
        self.menu = Terminal(self.home, size=(100, 30))
        self.menu.wait(KEYS, bound=60)
        self.drawn = time.time()               # it started before it drew
        self.bytes = self.home.root / "program-bytes"
        done = self.home.tmux("pipe-pane", "-t", self.menu.pane,
                              f"cat >{shlex.quote(str(self.bytes))}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)

    def said(self):
        return self.bytes.read_bytes() if self.bytes.exists() else b""

    def stamp(self):
        """An install: whole seconds, as install.sh stamps, past the second the menu started in."""
        while time.time() < int(self.drawn) + 1:
            time.sleep(0.05)
        self.home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")

    def left_held(self):
        """Where the old program's give under its hold ended, in the bytes."""
        return until(lambda: (held := HELD.search(self.said())) and held.end(), "held and left")

    def taken(self, since, count=2):
        """The bytes from the screen taken again past `since`, once the first `count` updates'
        marks after it are in, and those marks."""
        def came():
            said = self.said()
            enter = said.find(ENTER, since)
            marks = list(UPDATE.finditer(said, enter)) if enter >= 0 else []
            return (said, enter, marks) if len(marks) >= count else None
        return until(came, "took the screen and updated it")

    def restarted(self):
        """The menu started again, all of its first frame in; the bytes and where the hold ended."""
        self.stamp()
        left = self.left_held()
        said, enter, marks = self.taken(left, 3)
        self.assertEqual([mark.group() for mark in marks[:3]], [RELEASE, HOLD, RELEASE])
        return said, enter, marks

    def program(self):
        """The program's pid, one through its restart: the child of the terminal's shell."""
        for proc in Path("/proc").iterdir():
            try:
                parent = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[1])
                argv = (Path("/proc") / str(parent) / "cmdline").read_bytes().split(b"\0")
            except (ValueError, OSError, IndexError):
                continue
            if argv[2:3] == [KEEP.encode()] and argv[3:4] == [str(self.menu.status).encode()]:
                return int(proc.name)
        raise AssertionError("no program in the terminal")

    def nameless(self, pid):
        """The files no name reaches that `pid` holds open."""
        found = []
        for fd in Path(f"/proc/{pid}/fd").iterdir():
            try:
                link = os.readlink(fd)
            except OSError:
                continue
            if link.endswith(" (deleted)"):
                found.append(link)
        return found

    def in_seat(self):
        """The seat opened from the menu: the tmux client it started, its variables' names."""
        self.menu.keys("1")
        client = until(lambda: self.home.tmux("list-clients", "-F", "#{client_pid}").out.strip()
                       or None, "attached")
        names = {item.partition(b"=")[0] for item
                 in Path(f"/proc/{client}/environ").read_bytes().split(b"\0")}
        self.assertEqual(self.nameless(client), [])
        self.home.tmux("detach-client", "-s", f"={NAME}")
        return names

    def test_the_old_row_ends_the_hold_before_the_first_frame(self):
        said, enter, marks = self.restarted()
        release, start, end = marks[0].start(), marks[1].start(), marks[2].start()
        self.assertIn(ROW, said[enter:release])      # the old frame, as the screen is taken
        self.assertIn(ROW, said[start:end])          # ... and the first frame, all over again

    def test_no_line_grows_in_again(self):
        self.home.write(f".agentkit/state/plan-{NAME}.md", "- [x] Shipped it\n- [x] Shipped that\n")
        self.menu.wait("2 of 2")
        self.drawn = time.time()
        _said, _enter, marks = self.restarted()
        time.sleep(1)       # as ak opens a line grows for under that, a frame at a time
        later = self.said()[marks[2].end():].split(HOLD)
        # a read landing may write its row the once
        self.assertLessEqual(sum(BAR in update for update in later), 1, later)

    def test_a_terminal_resized_under_the_hold_gets_no_old_rows(self):
        # The new program takes this lock on its way to the terminal, so it waits there until the
        # terminal has its new size, as a slow start would.
        lock = (self.home.path / ".agentkit/state/watch.lock").open("a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        self.stamp()
        left = self.left_held()
        self.menu.resize(90, 25)
        tty = self.home.tmux("display-message", "-p", "-t", self.menu.pane, "#{pane_tty}",
                             server=SERVER).out.strip()
        fd = os.open(tty, os.O_RDONLY | os.O_NOCTTY)
        self.addCleanup(os.close, fd)
        until(lambda: tuple(os.get_terminal_size(fd)) == (90, 25), "resized")
        self.assertEqual(self.said().find(ENTER, left), -1, "took it before the resize")
        fcntl.flock(lock, fcntl.LOCK_UN)
        said, enter, marks = self.taken(left)
        self.assertEqual([mark.group() for mark in marks[:2]], [HOLD, RELEASE])
        self.assertNotIn(ROW, said[enter:marks[0].start()])
        self.assertIn(ROW, said[marks[0].start():marks[1].start()])

    def test_a_frame_the_terminal_was_resized_under_is_not_handed_on(self):
        # Stopped, the menu draws nothing for the new size before the install is there to see, and
        # the first thing it does on going on is start again.
        pid = self.program()
        os.kill(pid, signal.SIGSTOP)
        until(lambda: stopped(pid), "stopped")
        self.menu.resize(40, 15)
        self.stamp()
        os.kill(pid, signal.SIGCONT)
        said, enter, marks = self.taken(self.left_held())
        self.assertEqual([mark.group() for mark in marks[:2]], [HOLD, RELEASE])
        self.assertNotIn(ROW, said[enter:marks[0].start()])

    def test_what_the_menu_starts_after_a_restart_meets_none_of_it(self):
        before = self.in_seat()
        self.menu.wait(KEYS)
        self.drawn = time.time()
        self.restarted()
        self.menu.wait(KEYS)
        self.assertEqual(self.nameless(self.program()), [])
        self.assertEqual(self.in_seat(), before)

    def test_a_later_stop_and_going_on_writes_no_old_rows(self):
        since = len(self.restarted()[0])
        pid = self.program()
        os.kill(pid, signal.SIGTSTP)
        # A shell with job control would hold the menu stopped until `fg`; this terminal's has
        # none, and the system lets a stop nobody could undo pass, so only going on is seen.  It is
        # sent as `fg` is, once the menu has stopped or gone on by itself: sent while the menu is
        # still on its way to a stop of its own, it is lost and the menu stays stopped.
        def gave():
            said = self.said()
            back = said.find(LEAVE, since)
            return back >= 0 and (stopped(pid) or said.find(ENTER, back) >= 0)
        until(gave, "gave the terminal back and stopped")
        os.kill(pid, signal.SIGCONT)
        again = self.said().index(LEAVE, since)
        said, enter, marks = self.taken(again)
        self.assertEqual([mark.group() for mark in marks[:2]], [HOLD, RELEASE])
        self.assertNotIn(ROW, said[enter:marks[0].start()])


if __name__ == "__main__":
    unittest.main()
