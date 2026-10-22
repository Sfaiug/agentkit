"""On a terminal, bare `ak` takes the screen and gives it back as it found it, on Esc or a signal.

The menu draws on the alternate screen with the cursor hidden and every move of the pointer
reported, its keys read one at a time.  Whoever leaves it, kills it, hangs up on it or presses ^\\
must get back their own screen and a terminal that echoes their typing again, and ^Z must hand
the terminal over and take it again when the menu goes on.  The terminal is tmux
(tests/fixtures/akterm.py): its modes are read from tmux, the line discipline from the pane's
own tty, and what the program wrote from a pipe tmux opens on the pane before its first byte.
"""

import os
from pathlib import Path
import re
import resource
import signal
import sys
import termios
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import CONF, KEEP, SERVER, Terminal

# The alternate screen, the cursor shown, any-event pointer reports and their SGR form.
MODES = "#{alternate_on} #{cursor_flag} #{mouse_any_flag} #{mouse_sgr_flag}"
TAKEN, GIVEN = "1 0 1 1", "0 1 0 0"
LINES = termios.ICANON | termios.ECHO
QUERY = re.compile(rb"\x1b\]11;\?(?:\x1b\\|\x07)")    # what is your background colour (OSC 11)
LEFT, BACK = rb"\x1b\[\?1049l", rb"\x1b\[\?1049h"      # the alternate screen left, and taken


@unittest.skipUnless(REAL_TMUX and Path("/proc/self/stat").exists(), "needs tmux and /proc")
class MenuTerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # ^\ ends the menu as the system ends any quit, with a core dump: none is left behind.
        resource.setrlimit(resource.RLIMIT_CORE, (0, resource.getrlimit(resource.RLIMIT_CORE)[1]))
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        atoll = cls.home.path / "code" / "atoll"
        (atoll / ".git").mkdir(parents=True)
        Seat(cls.home, "atoll-ask", model="fable", screen="claude-question-pane.txt", cwd=atoll,
             record={"repo": str(atoll)})
        # The terminals' server up first, piping each new pane to a file of its own, so what
        # the program writes is kept from its first byte.
        cls.raw = cls.home.root / "raw"
        cls.raw.mkdir()
        conf = cls.home.root / "raw.conf"
        conf.write_text(CONF + "set -g exit-empty off\nset-hook -g after-new-session "
                        f"\"pipe-pane -O 'cat >>{cls.raw}/#{{pane_id}}'\"\n")
        cls.ask("-f", str(conf), "start-server")
        # A pane nothing ran in: its line discipline is the one the program finds in its own.
        cls.fresh = cls.ask("new-session", "-d", "-P", "-F", "#{pane_tty}", "sleep 86400")

    @classmethod
    def ask(cls, *args):
        done = cls.home.tmux(*args, server=SERVER)
        assert done.code == 0, done.err
        return done.out.strip()

    def open(self):
        # without colours, so the key line is written as one run of bytes
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        return term

    def assertModes(self, term, want, bound=30):
        """tmux takes in what the program wrote a moment after the program wrote it."""
        deadline = time.monotonic() + bound
        while ((shown := self.ask("display-message", "-p", "-t", term.pane, MODES)) != want
               and time.monotonic() < deadline):
            time.sleep(0.05)
        self.assertEqual(shown, want)

    def attrs(self, tty):
        fd = os.open(tty, os.O_RDWR | os.O_NOCTTY)
        try:
            return termios.tcgetattr(fd)
        finally:
            os.close(fd)

    def tty(self, term):
        return self.ask("display-message", "-p", "-t", term.pane, "#{pane_tty}")

    def written(self, term, until, since=0, bound=30):
        """What the program wrote from byte `since` once it holds `until`: the pipe gets it a
        moment after tmux draws it."""
        path, deadline = self.raw / term.pane, time.monotonic() + bound
        while True:
            out = path.read_bytes()[since:] if path.exists() else b""
            if re.search(until, out, re.S):
                return out
            if time.monotonic() > deadline:
                raise AssertionError(f"the program never wrote {until!r}; it wrote:\n{out!r}")
            time.sleep(0.05)

    def program(self, term):
        """The program's pid: the child of the terminal's shell that waits on it."""
        parents = {}
        for proc in Path("/proc").iterdir():
            try:
                parents[int(proc.name)] = int((proc / "stat").read_text().rsplit(")", 1)[1]
                                              .split()[1])
            except (ValueError, OSError, IndexError):
                continue
        for pid, parent in parents.items():
            try:
                argv = (Path("/proc") / str(parent) / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if argv[2:3] == [KEEP.encode()] and argv[3:4] == [str(term.status).encode()]:
                return pid
        raise AssertionError(f"no program runs in {term.pane}")

    def test_esc_gives_back_the_screen_modes_and_line_discipline_the_menu_found(self):
        term = self.open()
        self.assertModes(term, TAKEN)
        self.assertEqual(self.attrs(self.tty(term))[3] & LINES, 0)
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)
        self.assertModes(term, GIVEN)
        self.assertEqual(self.attrs(self.tty(term)), self.attrs(self.fresh))
        # The main screen as it was: every frame went to the alternate one.
        self.assertEqual(term.screen().strip(), "")
        # Asked once a start: each ask holds the first frame until the terminal answers.
        self.assertEqual(len(QUERY.findall(self.written(term, LEFT))), 1)

    def test_a_kill_a_hang_up_or_a_quit_gives_the_terminal_back_and_ends_the_menu(self):
        for name in ("SIGTERM", "SIGHUP", "SIGQUIT"):
            with self.subTest(name):
                number = getattr(signal, name)
                term = self.open()
                os.kill(self.program(term), number)
                # The shell reports a program a signal ended as 128 plus the signal's number.
                self.assertEqual(term.exit_code(), 128 + number)
                self.assertModes(term, GIVEN)
                self.assertEqual(self.attrs(self.tty(term)), self.attrs(self.fresh))

    def test_a_stop_gives_the_terminal_back_and_going_on_takes_it_again_and_redraws(self):
        term = self.open()
        since = len(self.written(term, rb"esc leave"))
        pid = self.program(term)
        os.kill(pid, signal.SIGTSTP)
        self.written(term, LEFT, since)
        # A shell with job control would hold the menu stopped until `fg`; this terminal's has
        # none, and the system lets a stop nobody could undo pass, so only going on is seen.
        os.kill(pid, signal.SIGCONT)
        self.written(term, LEFT + rb".*" + BACK + rb".*esc leave", since)
        self.assertModes(term, TAKEN)
        self.assertEqual(self.attrs(self.tty(term))[3] & LINES, 0)
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)
        self.assertModes(term, GIVEN)


if __name__ == "__main__":
    unittest.main()
