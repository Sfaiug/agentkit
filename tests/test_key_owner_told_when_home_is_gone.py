"""A standby's pass that fails with a reason pages the owner once every pass has failed for 20
minutes, by whichever of the machine's two clocks calls it younger, here from a first failed pass
as the copy is taken (tests/test_key_standby_pages_once_failing_on_end.py counts from others): one
page for each stamp of a pass that ended well, naming the home, the copy's age and why the pass
failed, as the pass printed it.  A page, sent or refused, changes nothing the pass prints, nor its
exit 1, and a refused one goes out at a later failed pass; whatever keeps the page from being
asked for, the pass says so in one line more.  No stamp, or one of another home, pages nobody.
Black-box, through tests/fixtures/twohomes.py, whose machine takes its clocks from AK_NOW (`wall
seconds-since-boot boot`), and tests/fixtures/sink.py, the owner's webhook.  A refused page's
retry is made due at once, as its wait passing leaves it.
"""

import json
from pathlib import Path
import re
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.sink import Sink
from fixtures.twohomes import Machines

WALL, SINCE, BOOT = 1789000000, 10000, "acme-boot-1"   # this machine's clocks at the pass
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well
OUTBOX = ".agentkit/state/notification-outbox"


def minutes(count):
    """An age of `count` minutes, a word of its own."""
    return rf"(?<![\w-]){count}m(?![\w-])"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TheOwnerIsToldWhenTheHomeIsGone(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        self.addCleanup(home.answer)
        here.client_of(home)
        self.sink = Sink(here)
        self.addCleanup(self.sink.close)
        done = self.passes(0)
        self.assertEqual(done.code, 0, done.out + done.err)
        home.silence()
        self.failed(0)

    def passes(self, wall, since=None):
        """A pass `wall` minutes after the first, by the wall clock, and by the clock since boot
        as many, or `since`."""
        since = wall if since is None else since
        self.here.env["AK_NOW"] = f"{WALL + wall * 60} {SINCE + since * 60} {BOOT}"
        return self.here.ak("standby", self.home.name, timeout=120)

    def failed(self, wall, since=None):
        """A pass that failed: its output, and why, as it printed it."""
        done = self.passes(wall, since)
        self.assertEqual(done.code, 1, done.out + done.err)
        why, = re.findall(rf"the pass from {self.home.name} failed: (.+)", done.err)
        return done, why

    def test_one_page_once_passes_failed_for_20_minutes(self):
        unpaged, _ = self.failed(19)
        self.assertEqual(self.sink.pages(), [])
        paged, why = self.failed(20)
        self.assertEqual((paged.out, paged.err), (unpaged.out, unpaged.err))
        page, = self.sink.pages()
        self.assertIn(self.home.name, page)
        self.assertRegex(page, minutes(20))
        self.assertIn(why, page)
        self.failed(23)
        self.failed(60)
        self.assertEqual(self.sink.pages(), [page])

    def test_a_refused_page_goes_out_at_a_later_failed_pass(self):
        unpaged, _ = self.failed(19)
        self.sink.script(503)
        refused, why = self.failed(20)
        self.assertEqual((refused.out, refused.err), (unpaged.out, unpaged.err))
        self.assertEqual(len(self.sink.pages()), 1)
        event, = (self.here.path / OUTBOX).glob("*.json")
        event.write_text(json.dumps({**json.loads(event.read_text()), "next_attempt": 0}))
        self.failed(23)
        _, page = self.sink.pages()
        self.assertIn(why, page)
        self.assertRegex(page, minutes(23))
        self.failed(60)
        self.assertEqual(len(self.sink.pages()), 2)

    def test_the_younger_clock_decides(self):
        self.failed(120, since=10)
        self.assertEqual(self.sink.pages(), [])

    def test_no_stamp_of_this_home_pages_nobody(self):
        stamp = self.here.path / STAMP
        stamp.write_text(f"{stamp.read_text().splitlines()[0]}\nacme-laptop\n")
        self.assertNotEqual(self.here.ak("standby").code, 0)    # no pass from it ended well
        self.failed(20)
        stamp.unlink()
        self.failed(23)
        self.assertEqual(self.sink.pages(), [])

    def test_an_owner_who_cannot_be_told_is_one_line_more(self):
        outbox = self.here.path / OUTBOX
        shutil.rmtree(outbox, ignore_errors=True)
        outbox.write_text("")
        done, why = self.failed(20)
        self.assertNotIn("Traceback (most recent call last):", done.err.splitlines())
        told, = done.err.split(f"failed: {why}\n", 1)[1].splitlines()
        self.assertRegex(told, r"^ak standby: the owner could not be told: \S")
        self.assertEqual(self.sink.pages(), [])


if __name__ == "__main__":
    unittest.main()
