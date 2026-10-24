"""A page the webhook did not take is tried again by a later tick, on a backoff and never sooner;
one it refused for good is never tried again; a rate limit's wait is kept, up to an hour.

The owner hears of a question only through the page: when the webhook is down the page waits in
the outbox and goes out once it is due, the same page, with no second one beside it; a webhook
that refuses what it was sent would refuse it again, so asking again only hammers it; and a rate
limit says how long to wait, which ak keeps without ever waiting past its own longest step.
Black-box: the program `AK_BIN` names runs a boxed `ak watch` from outside through
tests/fixtures/akbin.py, beside the record of a seat of tests/fixtures/akseat.py, paging
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

PAGE = {"username": "agentkit", "content": "🙋 Needs you · acme",
        "allowed_mentions": {"parse": []}}


def asking(home):
    """A Home whose next tick pages about seat acme."""
    akconfig.write(home, ["opus"])      # the audit off: a tick opens no seat of its own
    # A seat that closed with its question standing, its card held back by a tick five minutes
    # ago: nobody is in it, so its minute has passed.  A live seat's minute counts from its tmux
    # session's last activity, which no test can date back.  Its conversation is not its own,
    # so no tick reopens it to ask again.
    Seat(home, "acme", alive=False, record={"id_source": None})
    now = time.time()
    home.write(".agentkit/state/notify-acme.json",
               {"session": "acme", "kind": "needs", "text": "Which database should the app use?",
                "time": now - 300})
    home.write(".agentkit/state/card-acme.json",
               {"word": "needs you", "since": now - 300, "began": now - 300,
                "episode": "e" * 32, "sent": False})


def page_event(home):
    """The outbox's one event, the page about acme."""
    outbox = home.path / ".agentkit/state/notification-outbox"
    found = [json.loads(path.read_text()) for path in outbox.glob("*.json")]
    event, = [event for event in found if event.get("session") == "acme"]
    return event


def schedule(home, event, at):
    """Its next attempt at `at`, as a tick that long before or after it would find it."""
    home.write(f".agentkit/state/notification-outbox/{event['id']}.json",
               {**event, "next_attempt": at})


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ARefusedPage(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        asking(self.home)

    def tick(self):
        """One tick, and the clock once it is over."""
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        return time.time()

    def event(self):
        return page_event(self.home)

    def test_an_outage_keeps_the_page_and_only_a_tick_once_it_is_due_sends_it_again(self):
        self.sink.script(503)
        after = self.tick()
        event = self.event()
        self.assertEqual((event["status"], event["error"], event["attempts"]),
                         ("pending", "HTTP 503", 1))
        # the first step of the backoff, a minute, counted from the refusal
        self.assertGreaterEqual(event["next_attempt"], event["created_at"] + 60)
        self.assertLessEqual(event["next_attempt"], after + 60)
        # a tick before it is due, however slow the host was to start this one
        schedule(self.home, event, time.time() + 600)
        self.tick()
        self.assertEqual(len(self.sink.requests), 1)
        self.assertEqual(self.event()["attempts"], 1)
        schedule(self.home, event, time.time() - 1)
        self.tick()
        event = self.event()
        self.assertEqual((event["status"], event["attempts"], event["next_attempt"]),
                         ("delivered", 2, None))
        self.assertEqual(event["receipt"]["message_id"], "1002")
        refused, taken = self.sink.requests
        self.assertEqual((refused.method, taken.method), ("POST", "POST"))
        self.assertEqual(taken.body, refused.body)
        self.assertEqual(taken.json, PAGE)

    def test_a_refusal_for_good_blocks_the_page_and_no_later_tick_sends_it(self):
        self.sink.script(400, 400)
        self.tick()
        event = self.event()
        self.assertEqual((event["status"], event["error"], event["attempts"]),
                         ("blocked", "HTTP 400", 1))
        schedule(self.home, event, time.time() - 1)
        self.tick()
        self.assertEqual(len(self.sink.requests), 1)
        self.assertEqual((self.event()["status"], self.event()["attempts"]), ("blocked", 1))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ARateLimit(unittest.TestCase):
    def test_its_wait_is_kept_never_under_a_minute_and_never_over_an_hour(self):
        # the header's seconds, Discord's own in the body, and a wait shorter than the backoff
        cases = (({"Retry-After": "99999"}, None, 3600),
                 ({}, {"retry_after": 120}, 120),
                 ({"Retry-After": "1"}, None, 60))
        for headers, body, wait in cases:
            with self.subTest(headers=headers, body=body), Home() as home, Sink(home) as sink:
                sink.script((429, headers, body))
                asking(home)
                done = home.tick()
                self.assertEqual(done.code, 0, done.err)
                after = time.time()
                event = page_event(home)
                self.assertEqual((event["status"], event["error"], event["attempts"]),
                                 ("pending", "HTTP 429", 1))
                self.assertGreaterEqual(event["next_attempt"], event["created_at"] + wait)
                self.assertLessEqual(event["next_attempt"], after + wait)
                self.assertEqual(len(sink.requests), 1)


if __name__ == "__main__":
    unittest.main()
