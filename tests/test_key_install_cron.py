"""A server install keeps one tagged crontab line running `ak watch` every three minutes.

The tick is what moves every run, landing and stalled seat on the server, so each server
install owns the one live line: every line carrying the tag goes first, a copy the owner
commented out to pause the tick too, and the owner's other lines stay.  Every crontab exits 1
for an account with no table yet, which then gets one; any other failure is a table that could
not be read, and it stays as it is.  The record of a server goes after the crontab, so an install
cut short before then leaves a client, whose job installs again.  Black-box: install.sh
of the checkout `AK_BIN` names runs from outside in a Home of tests/fixtures/akbin.py made the
account's own by tests/fixtures/installer.py, so the install does what it does on a real host,
every tool it calls a fake and the crontab a table on disk.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

MINE = "0 4 * * * /usr/bin/true # the owner's nightly job"
PAUSED = "# */3 * * * * /srv/old/bin/ak watch # agentkit watch"
# a crontab that cannot read the table it keeps
UNREADABLE = """#!/bin/sh
case "$1" in
  -l) echo "crontab: cannot read the table" >&2; exit 2 ;;
  -) exec cat >{table} ;;
esac
"""
# an account with no table yet whose crontab notes, at its write, whether the record is there
NOTING = """#!/bin/sh
case "$1" in
  -l) exit 1 ;;
  -) if [ -f {record} ]; then echo there; else echo gone; fi >{note}; exec cat >{table} ;;
esac
"""

# A Mac install also loads a launch agent into the account's own launchd.
linux = unittest.skipUnless(sys.platform.startswith("linux"), "a Linux host's install")


def account(case):
    """A Home that is the account's own until `case`'s tests are done."""
    home = Home()
    case.addClassCleanup(home.close)
    installer.prepare(home)
    installer.own_home(home)
    return home


@linux
class WatchCron(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = account(cls)
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
        # each path one quoted word to sh, so a space in it splits nothing
        self.assertIn(f" '{installer.CHECKOUT / 'bin' / 'ak'}' watch ", line)
        self.assertIn(f">>'{self.home.path / '.agentkit/tmp/watch.log'}' 2>&1", line)
        # cron's own PATH holds neither ak nor a harness
        self.assertIn(f"PATH='{self.home.path / '.local/bin'}:", line)

    def test_a_second_install_leaves_the_table_as_it_was(self):
        self.assertEqual(self.table.read_text(), self.installed)


@linux
class Listing(unittest.TestCase):
    def test_an_exit_1_is_an_account_with_no_table_yet_which_gets_the_tick(self):
        home = account(self)
        done = installer.run(home, "--server")
        self.assertEqual(done.code, 0, done.out + done.err)
        lines = (home.root / "crontab").read_text().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].endswith(" # agentkit watch"), lines)

    def test_an_exit_2_leaves_the_owner_s_table_as_it_is_and_installs_nothing(self):
        home = account(self)
        table = home.root / "crontab"
        table.write_text(f"{MINE}\n")
        home.fake("crontab", UNREADABLE.format(table=shlex.quote(str(table))))
        done = installer.run(home, "--server")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(table.read_text(), f"{MINE}\n")
        self.assertIn("the ak watch cron is not installed", done.err)


@linux
class Record(unittest.TestCase):
    def test_the_record_of_a_server_goes_only_after_the_tick_is_written(self):
        home = account(self)
        record = home.path / ".agentkit/state/server"
        home.write(".agentkit/state/server", "acme-mini\n")
        table, note = home.root / "crontab", home.root / "note"
        q = lambda path: shlex.quote(str(path))
        home.fake("crontab", NOTING.format(record=q(record), note=q(note), table=q(table)))
        done = installer.run(home, "--server")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(table.read_text().endswith(" # agentkit watch\n"), table.read_text())
        self.assertEqual(note.read_text(), "there\n")
        self.assertFalse(record.exists())


if __name__ == "__main__":
    unittest.main()
