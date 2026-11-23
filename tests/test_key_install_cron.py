"""A server install keeps one tagged crontab line running `ak watch` every three minutes.

The tick is what moves every run, landing and stalled seat on the server, so each server
install owns the one live line: every line carrying the tag goes first, a copy the owner
commented out to pause the tick too, and the owner's other lines stay.  Every crontab exits 1
for an account with no table yet, which then gets one; any other failure is a table that could
not be read, and it stays as it is.  The record of a server goes only once the table holds the
tick, so an install cut short or refused before then leaves a client, whose job installs again.
Black-box: install.sh
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
# a crontab that keeps its table and refuses, noting so, every table it is given
REFUSING = """#!/bin/sh
case "$1" in
  -l) exec cat {table} ;;
  -) echo refused >>{note}; exit 1 ;;
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


def q(path):
    return shlex.quote(str(path))


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
    def setUp(self):
        self.home = account(self)
        self.record = self.home.path / ".agentkit/state/server"
        self.table, self.note = self.home.root / "crontab", self.home.root / "note"

    def server(self, crontab):
        """`install.sh --server`, which exits 0, on a machine with a record of a server."""
        self.home.write(".agentkit/state/server", "acme-mini\n")
        paths = dict(record=q(self.record), note=q(self.note), table=q(self.table))
        self.home.fake("crontab", crontab.format(**paths))
        done = installer.run(self.home, "--server")
        self.assertEqual(done.code, 0, done.out + done.err)

    def assertTicks(self):
        self.assertTrue(self.table.read_text().endswith(" # agentkit watch\n"), self.table.read_text())

    def test_the_record_of_a_server_goes_only_after_the_tick_is_written(self):
        self.server(NOTING)
        self.assertTicks()
        self.assertEqual(self.note.read_text(), "there\n")
        self.assertFalse(self.record.exists())

    def test_a_refused_table_leaves_the_record_which_the_install_after_it_removes(self):
        self.table.write_text(f"{MINE}\n")
        self.server(REFUSING)
        self.assertTrue(self.note.exists())
        self.assertEqual(self.table.read_text(), f"{MINE}\n")
        self.assertTrue(self.record.exists())
        self.server(installer.CRONTAB)
        self.assertTicks()
        self.assertFalse(self.record.exists())

    def test_a_table_that_cannot_be_read_leaves_the_record(self):
        self.server(UNREADABLE)
        self.assertFalse(self.table.exists())
        self.assertTrue(self.record.exists())

    def test_a_table_already_holding_the_tick_is_not_written_and_the_record_goes(self):
        self.server(installer.CRONTAB)
        self.assertTicks()
        self.server(REFUSING)
        self.assertFalse(self.note.exists())
        self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main()
