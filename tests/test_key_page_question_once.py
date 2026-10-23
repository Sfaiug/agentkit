"""A seat's open question pages the owner once, from the tick, with only its word and the seat.

Each tick's card pass pages a seat's question on record that no command paged, such as one the
seat kept back for its turn's end.  With the owner away from the seat for a minute and the
question standing for a minute, it sends `🙋 Needs you · acme` and nothing the seat said, since a
page is read on a phone or in a channel others see; the question stays in the seat and in the
outbox's record.  The next tick sends nothing more: one question is one page, however many
ticks see it standing.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, each tick boxed, before a seat of tests/fixtures/akseat.py, paging
tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink

QUESTION = "Which database should the app use?"
MINUTE = 60


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class QuestionPagedOnce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(home, ["opus"])
        Seat(home, "acme")
        opened = time.monotonic()
        # tmux keeps when someone last typed in or opened a seat, and nothing back-dates it:
        # the seat sits out the owner's minute in real time, once.
        time.sleep(max(0.0, opened + MINUTE + 0.5 - time.monotonic()))
        home.write(".agentkit/state/notify-acme.json",
                   {"session": "acme", "kind": "needs", "text": QUESTION,
                    "time": time.time() - 300})
        cls.ticks = []
        for _ in range(2):
            done = home.tick()
            assert done.code == 0, done.out + done.err
            cls.ticks.append(cls.sink.requests)

    def test_the_first_tick_pages_once_and_the_second_pages_nothing_more(self):
        first, second = self.ticks
        page, = first
        self.assertEqual(second, first)
        self.assertEqual((page.method, page.path, page.query), ("POST", "/hook", {"wait": "true"}))
        self.assertEqual(page.json, {"username": "agentkit", "content": "🙋 Needs you · acme",
                                     "allowed_mentions": {"parse": []}})

    def test_the_page_carries_nothing_the_seat_said(self):
        page, = self.ticks[-1]
        self.assertNotIn("database", page.body.decode().lower())

    def test_the_outbox_keeps_the_question_delivered_with_the_webhook_s_receipt(self):
        outbox = self.home.path / ".agentkit/state/notification-outbox"
        kept, = outbox.glob("*.json")
        self.assertRegex(kept.name, r"^[0-9a-f]{64}\.json$")
        event = json.loads(kept.read_text())
        self.assertEqual({key: event.get(key) for key in
                          ("session", "kind", "text", "message", "status", "attempts",
                           "next_attempt", "sink")},
                         {"session": "acme", "kind": "needs", "text": QUESTION,
                          "message": f"Needs you · acme: {QUESTION}", "status": "delivered",
                          "attempts": 1, "next_attempt": None, "sink": True})
        self.assertEqual(event["receipt"]["message_id"], "1001")

    def test_the_seat_s_card_says_needs_you_and_that_it_went(self):
        card = state(self.home, "card-acme.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", True))


if __name__ == "__main__":
    unittest.main()
