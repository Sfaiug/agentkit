"""`ak notify needs` keeps a seat's question and pages the owner with only its word and the seat.

The owner reads a page away from the seat, on a phone or in a channel others see: it says which
seat needs them and nothing the seat said, which stays in the seat, the only place it can be
answered.  The question is kept for the seat's row and bar, its card holds the episode so it is
paged once, and the outbox holds the page until it is delivered, with the webhook's receipt.  A
host with no webhook still records it all and says so, and the command succeeds: a seat asking
is never an error.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, before a seat of tests/fixtures/akseat.py, paging tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

QUESTION = "Which branch should the fix land on? It touches the parser."


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


def events(home, seat):
    """The outbox's events about that seat."""
    found = (json.loads(path.read_text())
             for path in (home.path / ".agentkit/state/notification-outbox").glob("*.json"))
    return [event for event in found if event.get("session") == seat]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WithoutAWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_the_question_its_card_and_one_event_are_kept_and_stderr_says_no_webhook(self):
        # a test's `off` or `dry-run`, and a host where nothing names a webhook at all
        for seat, sink in (("fix-api", "off"), ("fix-web", "dry-run"), ("fix-cli", None)):
            with self.subTest(sink=sink):
                Seat(self.home, seat)
                done = self.home.ak("notify", "needs", QUESTION, "--session", seat,
                                    env={"AK_NOTIFY_SINK": sink})
                self.assertEqual(done.code, 0, done.err)
                self.assertIn(f"notify: no webhook configured; message: Needs you · {seat}: "
                              f"{QUESTION}", done.err.splitlines())
                notice = state(self.home, f"notify-{seat}.json")
                self.assertEqual({key: notice.get(key) for key in
                                  ("session", "kind", "text", "source", "watcher")},
                                 {"session": seat, "kind": "needs", "text": QUESTION,
                                  "source": None, "watcher": False})
                self.assertIsInstance(notice["time"], (int, float))
                self.assertEqual(list(notice["asked_at"]), [QUESTION.lower()])
                card = state(self.home, f"card-{seat}.json")
                self.assertEqual(card["word"], "needs you")
                self.assertTrue(card["episode"])
                event, = events(self.home, seat)
                self.assertEqual((event["kind"], event["files"], event["status"]),
                                 ("needs", [], "disabled"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ToTheWebhook(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_the_page_keeps_the_webhook_s_query_and_its_receipt_is_recorded(self):
        sink = Sink(self.home, "/hook?thread_id=7")
        self.addCleanup(sink.close)
        sink.script((200, None, {"id": "42", "mentions": []}))
        Seat(self.home, "fix-api")
        done = self.home.ak("notify", "needs", "Which branch?", "--session", "fix-api")
        self.assertEqual(done.code, 0, done.err)
        sink.wait(1)
        page, = sink.requests
        self.assertEqual((page.method, page.path, page.query),
                         ("POST", "/hook", {"thread_id": "7", "wait": "true"}))
        self.assertEqual(page.json, {"username": "agentkit", "content": "🙋 Needs you · fix-api",
                                     "allowed_mentions": {"parse": []}})
        event, = events(self.home, "fix-api")
        self.assertEqual((event["status"], event["attempts"], event["receipt"]["message_id"]),
                         ("delivered", 1, "42"))
        self.assertIs(state(self.home, "card-fix-api.json")["sent"], True)

    def test_a_page_carries_its_word_the_seat_and_the_owner_s_mention_never_the_question(self):
        sink = Sink(self.home)
        self.addCleanup(sink.close)
        self.home.write(".agentkit/secrets/discord_user_id", "42\n")
        Seat(self.home, "acme")
        question = "Which schema should the parser read?"
        done = self.home.ak("notify", "needs", question, "--session", "acme")
        self.assertEqual(done.code, 0, done.err)
        sink.wait(1)
        page, = sink.requests
        self.assertEqual((page.path, page.query), ("/hook", {"wait": "true"}))
        self.assertEqual(page.json, {"username": "agentkit",
                                     "content": "🙋 Needs you · acme <@42>",
                                     "allowed_mentions": {"users": ["42"]}})
        self.assertNotIn("schema", repr(page).lower())
        card = state(self.home, "card-acme.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", True))
        self.assertEqual(state(self.home, "notify-acme.json")["text"], question)


if __name__ == "__main__":
    unittest.main()
