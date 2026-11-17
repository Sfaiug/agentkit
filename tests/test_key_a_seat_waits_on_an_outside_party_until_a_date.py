"""A seat waits on someone outside ak until a date: `ak wait until DATE "WHAT"`.

A store reviewing a listing is no question, run or pull request, so a seat waiting on one had
its stop sent back twice, then paged the owner as stuck.  Now, until its date, the seat's stop
stands and its row says what it waits on, in its own words, and until when; once the date has
come the tick ends the wait, the seat hears one line naming it, and its next stop with its plan
line still open goes back.  A date not in the future, or no words for what it waits on, is
refused and leaves the wait before as it was.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, its tick boxed, before a seat of tests/fixtures/akseat.py
whose hooks fire as Claude fires them (tests/fixtures/hookdrive.py), on the clock `AK_WAIT_CLOCK`
names (tests/fixtures/clock.py), in the Home's time zone, UTC.
"""

from calendar import timegm
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, hookdrive
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

NOW = timegm((2026, 11, 17, 12, 0, 0))
TOMORROW = "2026-11-18"
COMES = timegm((2026, 11, 18, 0, 0, 0))
WHAT = "the store's review"
SEAT = {"AGENTKIT_SESSION": "acme"}
# words a Claude composer shows whole (800 characters), but not in the line that would wake the
# seat on its date: that line is never typed
LONG = (WHAT + " of the acme listing, ") * 20


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASeatWaitsOnAnOutsidePartyUntilADate(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        clock.standing(self.home, "AK_WAIT_CLOCK", NOW)
        self.hooks = hookdrive.Hooks(self.home)
        # its plan's line open, a turn the owner gave it under way
        self.seat = Seat(self.home, "acme", screen="claude-working-pane.txt", planned=True)
        self.hooks.prompt("Ship the acme listing.", self.seat)
        waited = self.home.ak("wait", "until", TOMORROW, WHAT, env=SEAT)
        self.assertEqual((waited.code, waited.out),
                         (0, f"acme: waiting on {WHAT} until {TOMORROW}\n"), waited.err)

    def stop(self, closing):
        """The reason the seat's Stop on `closing` went back with, None where it stood."""
        self.seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(self.home, self.seat.name, closing)
        fired = self.hooks.fire("Stop", {"background_tasks": [], "stop_hook_active": False,
                                         "transcript_path": chat}, seat="acme", pane=self.seat)
        self.assertEqual(fired.code, 0, fired.err)
        blocks = [out["reason"] for out in fired.said if out.get("decision") == "block"]
        return blocks[0] if blocks else None

    def row(self):
        """The seat's word and its reason, as its row has them."""
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        word = why.out.splitlines()[0].split(None, 1)[1].strip()
        return word, re.search(r"(?m)^  reason: +(.*)$", why.out).group(1)

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def heard(self):
        return [line for line in self.seat.lines() if WHAT in line]

    def test_its_stop_stands_until_the_date_which_wakes_it_once(self):
        self.assertIsNone(self.stop("Waiting on the store's review of the listing."))
        self.assertEqual(self.row(), ("working", f"waiting on {WHAT} until {TOMORROW}"))
        self.tick()
        self.assertEqual(self.seat.lines(), [])
        self.assertEqual(self.row(), ("working", f"waiting on {WHAT} until {TOMORROW}"))
        clock.standing(self.home, "AK_WAIT_CLOCK", COMES)
        self.tick()
        self.seat.wait_lines(1)
        self.tick()
        line, = self.heard()
        # the harness takes the line as its next turn, which ends with the line still open
        self.hooks.prompt(line, self.seat)
        self.assertIsNotNone(self.stop("The store has not answered yet."))

    def test_a_past_date_no_words_or_too_many_is_refused_and_the_wait_before_stays(self):
        for args in (("until", "2026-11-16", "the provider's answer"),
                     ("until", "2026-11-17 11:59", "the provider's answer"),
                     ("until", "2026-11-17", "the provider's answer"),
                     ("until", TOMORROW), ("until", TOMORROW, "  "),
                     ("until", "next week", "the provider's answer"),
                     ("until", TOMORROW, LONG[:780])):
            with self.subTest(args=args):
                done = self.home.ak("wait", *args, env=SEAT)
                self.assertNotEqual(done.code, 0, done.out)
                self.assertEqual(done.out, "")
                self.assertEqual(len(done.err.splitlines()), 1, done.err)
                self.assertEqual(self.row(), ("working", f"waiting on {WHAT} until {TOMORROW}"))
        self.assertIsNone(self.stop("Waiting on the store's review of the listing."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
