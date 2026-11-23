"""A standby's pass whose `install.sh --server` exited 0 (tests/test_key_standby_becomes_home.py)
pages the owner, once for each lease it took, naming this machine and the one it took over from:
one whose crontab refused the tick's row, which leaves a client, pages, and the pass after it, which
makes the machine the home, pages no more.  A pass whose install exited 1 pages nobody, nor does
one that finds the home's lease; one whose page the webhook refused exits 0 still.

Black-box: the program `AK_BIN` runs on the machines, passes and install of
tests/test_key_standby_becomes_home.py, each case its own and each machine's clock from AK_NOW, and
tests/fixtures/sink.py is the standby's webhook.  What came back is each pass's exit, as that key
reads it with the record of a server and the crontab, and the pages the webhook took, of each only
that it names acme-vm and acme-mini.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.sink import Sink
import test_key_standby_becomes_home as becoming
from test_key_standby_becomes_home import REFUSING


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TheOwnerIsToldOfATakeover(unittest.TestCase):
    # the machines, their passes and the lease the standby takes, the key of a standby becoming
    # home's own: its class reached through its module, so this file runs none of its cases
    own = becoming.AStandbyBecomesHome
    fire, lease, passes, kept, notes = own.fire, own.lease, own.passes, own.kept, own.notes
    took, becomes_home, stays = own.took, own.becomes_home, own.stays

    def setUp(self):
        self.own.setUp(self)
        self.sink = Sink(self.standby)
        self.addCleanup(self.sink.close)

    def told(self, count):
        """That the webhook took `count` pages, each naming both machines."""
        pages = self.sink.pages()
        self.assertEqual(len(pages), count, pages)
        for page in pages:
            self.assertIn("acme-vm", page)
            self.assertIn("acme-mini", page)

    def test_a_pass_that_makes_the_standby_home_pages_once(self):
        self.becomes_home(24, self.took())
        self.told(1)

    def test_a_pass_that_left_a_client_pages_and_the_next_for_that_lease_does_not(self):
        before = self.took()
        crontab = self.standby.bin / "crontab"
        working = crontab.read_text()
        self.standby.fake("crontab", REFUSING.format(
            table=shlex.quote(str(self.standby.at / "crontab"))))
        self.stays(24, before)
        self.told(1)
        self.standby.fake("crontab", working)
        self.becomes_home(27, before)
        self.told(1)

    def test_an_install_that_fails_pages_nobody(self):
        before = self.took()
        (self.standby.install.path / "install.sh").write_bytes(b"#!/bin/sh\nexit 1\n")
        self.assertEqual(self.stays(24, before), 1)
        self.told(0)

    def test_a_refused_page_leaves_the_pass_exiting_0(self):
        self.sink.script(503)
        self.becomes_home(24, self.took())
        self.told(1)

    def test_a_pass_finding_the_homes_lease_pages_nobody(self):
        self.took(fired=True)
        self.assertEqual(self.passes(24), 0)
        self.told(0)


if __name__ == "__main__":
    unittest.main()
