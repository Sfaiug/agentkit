"""A standby's failed passes page the owner once every pass has failed for 20 minutes on end,
counted from the first to fail after the last that ended well, whatever the copy's age: the page
names the copy's age then.  A pass that ends well ends the count, and a count kept cut short, or
none that can be kept, begins it anew, which pages nobody early and changes nothing a pass prints
nor its exit.  Black-box, through tests/fixtures/twohomes.py, whose machine takes its clocks from
AK_NOW (`wall seconds-since-boot boot`), and tests/fixtures/sink.py, the owner's webhook.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.sink import Sink
from fixtures.twohomes import Machines

WALL, SINCE, BOOT = 1789000000, 10000, "acme-boot-1"   # this machine's clocks at the pass
FAILING = ".agentkit/tmp/standby/failing"      # when the first pass to fail after the stamp failed


def minutes(count):
    """An age of `count` minutes, a word of its own."""
    return rf"(?<![\w-]){count}m(?![\w-])"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class FailedPassesPageOnceFailingOnEnd(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        self.addCleanup(home.answer)
        here.client_of(home)
        self.sink = Sink(here)
        self.addCleanup(self.sink.close)
        self.ended_well(0)

    def passes(self, wall):
        """A pass `wall` minutes after the first, by both clocks."""
        self.here.env["AK_NOW"] = f"{WALL + wall * 60} {SINCE + wall * 60} {BOOT}"
        return self.here.ak("standby", self.home.name, timeout=120)

    def ended_well(self, wall):
        """A pass that ended well, the home silent after it."""
        self.home.answer()
        done = self.passes(wall)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.home.silence()

    def failed(self, wall):
        """A pass that failed: its output, and why, as it printed it."""
        done = self.passes(wall)
        self.assertEqual(done.code, 1, done.out + done.err)
        why, = re.findall(rf"the pass from {self.home.name} failed: (.+)", done.err)
        return done, why

    def test_the_count_begins_at_the_first_failed_pass(self):
        unpaged, _ = self.failed(25)
        self.failed(44)
        self.assertEqual(self.sink.pages(), [])
        paged, why = self.failed(45)
        self.assertEqual((paged.out, paged.err), (unpaged.out, unpaged.err))
        page, = self.sink.pages()
        self.assertIn(self.home.name, page)
        self.assertRegex(page, minutes(45))
        self.assertIn(why, page)

    def test_a_pass_that_ended_well_begins_the_count_again(self):
        self.failed(25)
        self.ended_well(40)
        self.failed(45)
        self.failed(64)
        self.assertEqual(self.sink.pages(), [])
        self.failed(65)
        page, = self.sink.pages()
        self.assertRegex(page, minutes(25))

    def test_a_count_cut_short_begins_anew(self):
        unpaged, _ = self.failed(25)
        failing = self.here.path / FAILING
        failing.write_text(failing.read_text().splitlines()[0] + "\n")
        anew, _ = self.failed(45)
        self.assertEqual((anew.out, anew.err), (unpaged.out, unpaged.err))
        self.failed(64)
        self.assertEqual(self.sink.pages(), [])
        self.failed(65)
        self.assertEqual(len(self.sink.pages()), 1)

    def test_a_count_that_cannot_be_kept_pages_nobody_and_changes_nothing(self):
        unpaged, _ = self.failed(25)
        failing = self.here.path / FAILING
        failing.unlink()
        failing.mkdir()
        unkept, _ = self.failed(45)
        self.assertEqual((unkept.out, unkept.err), (unpaged.out, unpaged.err))
        self.failed(90)
        self.assertEqual(self.sink.pages(), [])


if __name__ == "__main__":
    unittest.main()
