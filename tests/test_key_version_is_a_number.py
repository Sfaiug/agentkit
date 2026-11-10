"""ak's version is how many commits its checkout's history holds, then its date: `Version 3 ·
2026-09-29` under `c`, and the same in `ak update --dry-run`.  Each change merged to main is one
commit, so the number goes up by one with each and a higher one is the newer ak; a history cut
short, a shallow clone, cannot be counted and says its date alone, never a number that is wrong.
No line holds the commit's hash, which nobody reads.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) and run
from outside through tests/fixtures/akbin.py, its ~/agentkit a repository this test makes and
its harness a fake of tests/fixtures/fakeadapter.py; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

DAY = "2026-09-29T12:00:00+0000"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class VersionIsANumber(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"fable": "claude"})
        fakeadapter.install(self.home, claude="pass")
        self.checkout = self.home.path / "agentkit"
        self.git("init", "-q", str(self.checkout))
        for _ in range(3):
            self.commit()

    def git(self, *args):
        done = self.home.run("git", *args, env={"GIT_AUTHOR_DATE": DAY, "GIT_COMMITTER_DATE": DAY})
        self.assertEqual(done.code, 0, done.err)

    def commit(self):
        self.git("-C", str(self.checkout), "commit", "-q", "--allow-empty", "-m", "change")

    def version(self, menu):
        """The version line `c` shows, back on the main screen after."""
        menu.keys("c")
        screen = menu.wait(lambda screen: "Version " in screen)
        menu.keys("Escape")
        menu.wait(lambda screen: "Version " not in screen and "c config" in screen)
        return next(line.strip() for line in screen.splitlines() if "Version " in line)

    def test_the_version_counts_the_commits_and_a_history_cut_short_says_its_date(self):
        menu = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        menu.wait("c config")
        self.assertEqual(self.version(menu), "Version 3 · 2026-09-29")
        done = self.home.ak("update", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        said = [line for line in done.out.splitlines() if line.startswith("update: agentkit")]
        self.assertEqual(len(said), 1, done.out)
        self.assertTrue(said[0].startswith("update: agentkit 3 · 2026-09-29: "), said)

        self.commit()
        self.assertEqual(self.version(menu), "Version 4 · 2026-09-29")

        full = self.home.root / "full"
        self.checkout.rename(full)
        self.git("clone", "-q", "--depth", "1", full.as_uri(), str(self.checkout))
        self.assertEqual(self.version(menu), "Version 2026-09-29")


if __name__ == "__main__":
    unittest.main()
