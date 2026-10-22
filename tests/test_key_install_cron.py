"""A server install keeps one tagged crontab line running `ak watch` every three minutes.

The tick is what moves every run, landing and stalled seat on the server, so each server
install owns the one live line: every line carrying the tag goes first, a copy the owner
commented out to pause the tick too, and the owner's other lines stay.  Black-box: install.sh
of the checkout `AK_BIN` names runs from outside in a Home of tests/fixtures/akbin.py made the
account's own by tests/fixtures/installer.py, so the install does what it does on a real host,
every tool it calls a fake and the crontab a table on disk.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

MINE = "0 4 * * * /usr/bin/true # the owner's nightly job"
PAUSED = "# */3 * * * * /srv/old/bin/ak watch # agentkit watch"


# A Mac install also loads a launch agent into the account's own launchd.
@unittest.skipUnless(sys.platform.startswith("linux"), "a Linux host's install")
class WatchCron(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        installer.prepare(home)
        installer.own_home(home)
        cls.table = home.root / "crontab"
        cls.table.write_text(f"{MINE}\n{PAUSED}\n")
        cls.first = installer.run(home, "--server")
        cls.installed = cls.table.read_text()
        cls.second = installer.run(home)

    def test_both_installs_succeed(self):
        for done in (self.first, self.second):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_one_tagged_line_runs_the_program_s_watch_every_three_minutes(self):
        lines = self.installed.splitlines()
        self.assertEqual(lines[0], MINE)
        tagged = [line for line in lines if "agentkit watch" in line]
        self.assertEqual(len(tagged), 1, lines)
        line = tagged[0]
        self.assertTrue(line.startswith("*/3 * * * * "), line)
        self.assertTrue(line.endswith(" # agentkit watch"), line)
        self.assertIn(f" {installer.CHECKOUT / 'bin' / 'ak'} watch ", line)
        self.assertIn(f">>{self.home.path / '.agentkit/tmp/watch.log'} 2>&1", line)
        # cron's own PATH holds neither ak nor a harness
        self.assertIn(f"PATH={self.home.path / '.local/bin'}:", line)

    def test_a_second_install_leaves_the_table_as_it_was(self):
        self.assertEqual(self.table.read_text(), self.installed)


if __name__ == "__main__":
    unittest.main()
