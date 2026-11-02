"""An open menu looks at every checkout under ~/code at every read, and asks git about a worktree
only once while its `.git` and what that leads to read the same: a worktree costs no process per
read, and still stays under its project when the repository moves and `.git` is linked anew.
Black-box: the program `AK_BIN` names runs in a person's terminal (tests/fixtures/akterm.py), with
a `git` first on its PATH that notes where it runs, and is judged by the headings it draws.
"""

import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SYSTEM, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

GIT = shutil.which("git", path=":".join(SYSTEM))
SETTLED = 1.5      # s: a `.git` changed within the last second vouches for no answer
OPENS = 60         # the first draw looks at every seat, which a loaded host makes slow


def headings(screen):
    """The projects drawn, each heading a row of its own."""
    return [line.strip() for line in screen.splitlines()
            if line.strip() in ("acme", "fix-api", "fix-web")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AskedOnce(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.ran = home.root / "git-ran"
        self.first, self.second = home.root / "first", home.root / "second"
        self.first.mkdir()
        code = home.path / "code"
        self.acme, self.fix, self.web = code / "acme", code / "fix-api", code / "fix-web"
        self.git("init", "-q", "-b", "main", "--separate-git-dir", self.first / "acme.git",
                 self.acme)
        self.git("-C", self.acme, "commit", "-q", "--allow-empty", "-m", "seed")
        self.git("-C", self.acme, "worktree", "add", "-q", "-b", "fix-api", self.fix)
        self.git("-C", self.acme, "worktree", "add", "-q", "-b", "fix-web", self.web)
        self.private = Path((self.fix / ".git").read_text().removeprefix("gitdir: ").strip())
        (self.fix / ".git").unlink()
        (self.fix / ".git").symlink_to(self.private, target_is_directory=True)
        home.fake("git", f'#!/bin/sh\npwd -P >>"{self.ran}"\nexec "{GIT}" "$@"\n')
        Seat(home, "atoll-main", cwd=self.acme, record={"repo": str(self.acme)})
        Seat(home, "atoll-fix", cwd=self.fix, record={"repo": str(self.fix)})
        self.menu = Terminal(home, size=(100, 40))
        self.menu.wait("atoll-fix", bound=OPENS)

    def git(self, *args):
        done = self.home.run("git", "-c", "user.name=acme", "-c", "user.email=acme@example.com",
                             *map(str, args))
        self.assertEqual(done.code, 0, done.err)

    def read_again(self, name):
        """What the menu draws once a read has passed: one that shows a seat added just now."""
        Seat(self.home, name, cwd=self.acme, record={"repo": str(self.acme)})
        return self.menu.wait(name)

    def asked_in(self, path):
        lines = self.ran.read_text().splitlines() if self.ran.exists() else []
        return lines.count(str(path.resolve()))

    def test_reads_with_nothing_changed_ask_git_nothing_about_a_worktree(self):
        time.sleep(SETTLED)
        self.read_again("atoll-two")
        asked = self.asked_in(self.web)
        self.read_again("atoll-three")
        self.read_again("atoll-four")
        self.assertEqual(self.asked_in(self.web), asked)

    def test_a_repository_moved_and_linked_anew_keeps_its_worktree_under_it(self):
        self.assertEqual(headings(self.read_again("atoll-two")), ["acme"])
        time.sleep(SETTLED)
        self.read_again("atoll-three")      # the worktree's answer is kept by now
        self.first.rename(self.second)
        (self.acme / ".git").write_text(f"gitdir: {self.second / 'acme.git'}\n")
        (self.fix / ".git").unlink()
        (self.fix / ".git").symlink_to(self.second / self.private.relative_to(self.first),
                                       target_is_directory=True)
        self.assertEqual(headings(self.read_again("atoll-four")), ["acme"])


if __name__ == "__main__":
    unittest.main()
