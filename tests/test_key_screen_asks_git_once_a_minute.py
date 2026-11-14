"""A still screen asks git about a checkout at most once a minute, and still files each worktree
under its project, one added while it is open at once.

Every read asked git about every worktree under ~/code: 80 processes in 170 s on a host, growing
with the worktrees a home holds.  Black-box: the program `AK_BIN` names runs in a person's terminal
(tests/fixtures/akterm.py) with a `git` first on its PATH that logs each call's working directory
and runs the real one.  What holds git's answer in a pass, and nowhere else, is
tests/test_held_answers.py.
"""

import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, SYSTEM, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))
MINUTE = 60
READS = 6         # at least: touching what a screen watches this many times over the minute
BOUND = 120       # a read a loaded host takes long over


def row(name, word=""):
    """A test of a screen: that seat has a row, reading `word`."""
    return lambda screen: re.search(rf"^[› ] +\d+  {re.escape(name)} .*{word}", screen, re.M)


def under(screen, heading, name):
    """Whether that seat's row is under that project's heading: the last line above it starting at
    the screen's edge, which only the pointed-at row's `›` does besides."""
    lines = screen.splitlines()
    place = next(n for n, line in enumerate(lines) if row(name)(line))
    return [line for line in lines[:place] if re.match(r"[^\s›]", line)][-1].split()[0] == heading


@unittest.skipUnless(REAL_TMUX and GIT, "no tmux or no git")
class ScreenAsksGitOnceAMinute(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        self.acme = home.path / "code" / "acme"
        self.acme.mkdir(parents=True)
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "init")
        self.add("fix-api")
        self.calls = home.log("git")
        home.fake("git", f"#!/bin/sh\npwd -P >>{shlex.quote(str(self.calls))}\n"
                         f'exec {shlex.quote(GIT)} "$@"\n')
        self.menu = Terminal(home, "--client", size=(100, 40))
        self.menu.wait(row("fix-api"), bound=BOUND)
        self.reads = 0

    def git(self, *args):
        done = self.home.run(GIT, *args, cwd=self.acme)
        self.assertEqual(done.code, 0, done.err)

    def add(self, name):
        """A worktree of acme under code/, and a seat in it."""
        where = self.acme.parent / name
        self.git("worktree", "add", "-q", "-b", name, str(where))
        Seat(self.home, name, cwd=where, record={"repo": str(where)})

    def asked(self, name):
        """How many times git has run in that worktree."""
        where = str(self.acme.parent / name)
        return self.calls.read_text().splitlines().count(where) if self.calls.exists() else 0

    def read(self):
        """One read and what it drew: a run of the seat's goes or ends, as the screen sees by the
        mark every run's move touches (`menu.recorded`), and the row says so."""
        self.reads += 1
        over = self.reads % 2 == 0
        self.home.write(".agentkit/runs/20261102-0001-fix/run.json", {
            "run_id": "20261102-0001-fix", "title": "fix", "launched_session": "fix-api",
            "branch": "ak/fix", "started_at": time.time(), "step": "executor",
            "state": "pass" if over else "running", "verdict": "PASS" if over else None,
            "merged": over, "finished_at": time.time() if over else None,
            "handed_back": time.time() if over else None, "reported": over,
            # no loop runs it: without this the maintenance an opening screen starts behind its
            # first frame, if it reaches the record, reaps it to `interrupted`, never `working`
            "resume_after": None if over else time.time() + BOUND})
        (self.home.path / ".agentkit/state/runs-moved").touch()
        working = row("fix-api", "● working")
        return self.menu.wait((lambda screen: row("fix-api")(screen) and not working(screen))
                              if over else working, bound=BOUND)

    def test_1_a_still_screen_asks_at_most_twice_in_a_minute(self):
        start, before = time.monotonic(), self.asked("fix-api")
        for n in range(READS):
            self.assertTrue(under(self.read(), "acme", "fix-api"), self.menu.screen())
            time.sleep(max(0, start + (n + 1) * MINUTE / READS - time.monotonic()))
        # a hold starts each one a minute from the last, however long a loaded host took over this
        self.assertLessEqual(self.asked("fix-api") - before,
                             1 + (time.monotonic() - start) // MINUTE)

    def test_2_a_worktree_added_while_it_is_open_is_filed_at_its_first_read(self):
        self.read()
        self.add("fix-web")
        screen = self.menu.wait(row("fix-web"), bound=BOUND)
        self.assertTrue(under(screen, "acme", "fix-web"), screen)
        self.assertTrue(under(screen, "acme", "fix-api"), screen)


if __name__ == "__main__":
    unittest.main()
