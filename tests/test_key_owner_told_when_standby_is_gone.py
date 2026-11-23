"""A firing of a home's tick, `ak watch`, pages the owner once a machine's copy of it is an hour
old, by whichever of the home's two clocks calls it younger: one page for each stamp a record
holds, naming that machine and the copy's age, however often the tick fires after.  A page the
webhook refused goes out at a later firing, and a record the machine writes again pages once more
an hour on.  A record that holds no stamp pages nobody, nor does a home with no record, nor a
client, whatever its folder holds; and neither a page nor anything it meets changes a firing's
exit.  No output of a firing is compared: what a tick prints varies with the clock.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, each
machine's clocks from AK_NOW (`wall seconds-since-boot boot`), and tests/fixtures/sink.py is the
owner's webhook.  A record is written as a pass that ended well leaves it, by `ak standby
--began` and `--copied HOST WALL SINCE BOOT yes`.  A refused page's retry is made due at once, as
its wait passing leaves it.
"""

import json
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.sink import Sink
from fixtures.twohomes import Machines

WALL, SINCE, BOOT = 1789000000, 10000, "acme-boot-1"   # the home's clocks at the record
HOST = "acme-laptop"    # the machine that says it copied the home
RECORDS = Path(".agentkit/tmp/copies")      # the home's records of the machines that copy it
OUTBOX = Path(".agentkit/state/notification-outbox")
HOUR = r"(?<![\w-])1h(?![\w-])"     # an age of an hour, a word of its own
DAY = 24 * 60


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TheOwnerIsToldWhenAStandbyIsGone(unittest.TestCase):
    def machines(self, *names):
        """Machines of these names, or one home, each paging a sink of its own."""
        machines = Machines(*(names or ("acme-mini",)))
        self.addCleanup(machines.close)
        self.sinks = {}
        for machine in machines:
            self.sinks[machine.name] = sink = Sink(machine)
            self.addCleanup(sink.close)
        return machines

    def at(self, machine, wall, since=None):
        """`machine`'s clocks `wall` minutes after the first record, and since boot as many, or
        `since`."""
        since = wall if since is None else since
        machine.env["AK_NOW"] = f"{WALL + wall * 60} {SINCE + since * 60} {BOOT}"

    def record(self, machine, minute):
        """HOST's record on `machine` at `minute`, as a pass that ended well leaves it."""
        self.at(machine, minute)
        began = machine.ak("standby", "--began")
        kept = machine.ak("standby", "--copied", HOST, *began.out.split(), "yes")
        self.assertEqual((began.code, kept.code), (0, 0), began.err + kept.err)

    def fires(self, machine, wall, since=None):
        """A firing of `machine`'s tick at `wall` minutes: its exit."""
        self.at(machine, wall, since)
        return machine.tick().code

    def pages(self, machine):
        return self.sinks[machine.name].pages()

    def told(self, page):
        """A page naming HOST and an age of an hour."""
        self.assertIn(HOST, page)
        self.assertRegex(page, HOUR)

    def test_one_page_once_the_copy_is_an_hour_old(self):
        home, = self.machines()
        self.record(home, 0)
        self.fires(home, 59)
        self.assertEqual(self.pages(home), [])
        self.fires(home, 60)
        page, = self.pages(home)
        self.told(page)
        self.fires(home, 63)
        self.fires(home, DAY)
        self.assertEqual(self.pages(home), [page])

    def test_a_refused_page_goes_out_at_a_later_firing(self):
        home, = self.machines()
        self.record(home, 0)
        self.sinks[home.name].script(503)
        self.assertEqual(self.fires(home, 60), 0)
        self.assertEqual(len(self.pages(home)), 1)
        event, = (home.path / OUTBOX).glob("*.json")
        event.write_text(json.dumps({**json.loads(event.read_text()), "next_attempt": 0}))
        self.fires(home, 63)
        _, page = self.pages(home)
        self.told(page)
        self.fires(home, DAY)
        self.assertEqual(len(self.pages(home)), 2)

    def test_a_record_written_again_pages_again_an_hour_on(self):
        home, = self.machines()
        self.record(home, 0)
        self.fires(home, 60)
        self.record(home, 65)
        self.fires(home, 124)
        self.assertEqual(len(self.pages(home)), 1)
        self.fires(home, 125)
        _, page = self.pages(home)
        self.told(page)

    def test_the_younger_clock_decides(self):
        home, = self.machines()
        self.record(home, 0)
        self.fires(home, 120, since=10)
        self.assertEqual(self.pages(home), [])

    def test_no_record_and_a_client_page_nobody(self):
        home, client = self.machines("acme-mini", "acme-vm")
        client.client_of(home)
        self.record(client, 0)
        self.fires(home, DAY)
        self.fires(client, DAY)
        self.assertEqual((self.pages(home), self.pages(client)), ([], []))

    def test_a_record_holding_no_stamp_pages_nobody(self):
        home, = self.machines()
        home.write(RECORDS / HOST, "acme\nno\n")
        self.assertEqual(self.fires(home, DAY), 0)
        self.assertEqual(self.pages(home), [])

    def test_an_owner_who_cannot_be_told_changes_no_exit(self):
        recorded, bare = self.machines("acme-mini", "acme-mac")
        self.record(recorded, 0)
        for home in (recorded, bare):
            shutil.rmtree(home.path / OUTBOX, ignore_errors=True)
            home.write(OUTBOX, "")
        self.assertEqual(self.fires(recorded, DAY), self.fires(bare, DAY))


if __name__ == "__main__":
    unittest.main()
