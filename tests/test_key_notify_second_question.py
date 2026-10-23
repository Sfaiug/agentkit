"""A seat's second question, asked while its first stands unanswered, joins it: one card, one page.

A seat often asks again before the owner has come: another question, or the same one once more.
The owner is paged once for the episode, the page saying only that the seat needs them, and
reads every question in the seat, in the order asked, each once: the notice keeps them all,
joined with ` Also: `, and the card already out stays the only one.  The same question asked
again, in any case or spacing, keeps its first words and is dated anew.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, before a seat of
tests/fixtures/akseat.py, paging tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

FIRST, SECOND = "Which branch?", "Should I also bump the version?"


def state(home, name):
    return json.loads((home.path / ".agentkit" / "state" / name).read_text())


def events(home, seat):
    """The outbox's events about that seat."""
    found = (json.loads(path.read_text())
             for path in (home.path / ".agentkit/state/notification-outbox").glob("*.json"))
    return [event for event in found if event.get("session") == seat]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SecondQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)

    def ask(self, seat, question):
        done = self.home.ak("notify", "needs", question, "--session", seat)
        self.assertEqual(done.code, 0, done.err)

    def paged(self, seat):
        return self.sink.pages().count(f"🙋 Needs you · {seat}")

    def opened(self, seat):
        """A seat that asked FIRST and was paged for it."""
        Seat(self.home, seat)
        before = len(self.sink.requests)
        self.ask(seat, FIRST)
        self.sink.wait(before + 1)
        self.assertEqual(self.paged(seat), 1)
        return state(self.home, f"card-{seat}.json")

    def test_a_different_question_joins_the_open_one_and_pages_nothing_more(self):
        card = self.opened("fix-api")
        self.ask("fix-api", SECOND)
        notice = state(self.home, "notify-fix-api.json")
        self.assertEqual(notice["text"], f"{FIRST} Also: {SECOND}")
        self.assertEqual(notice["questions"], [FIRST, SECOND])
        self.assertEqual(list(notice["asked_at"]), [FIRST.lower(), SECOND.lower()])
        self.assertEqual(self.paged("fix-api"), 1)
        again = state(self.home, "card-fix-api.json")
        self.assertEqual((again["word"], again["episode"], again["sent"]),
                         ("needs you", card["episode"], True))
        self.assertEqual(len(events(self.home, "fix-api")), 1)

    def test_a_question_asked_again_keeps_its_words_and_place_and_is_dated_anew(self):
        self.opened("fix-web")
        self.ask("fix-web", SECOND)
        for again in (FIRST, "which   BRANCH?"):
            with self.subTest(again=again):
                dated = state(self.home, "notify-fix-web.json")["asked_at"][FIRST.lower()]
                self.ask("fix-web", again)
                notice = state(self.home, "notify-fix-web.json")
                self.assertEqual((notice["text"], notice["questions"]),
                                 (f"{FIRST} Also: {SECOND}", [FIRST, SECOND]))
                self.assertGreater(notice["asked_at"][FIRST.lower()], dated)
                self.assertEqual(self.paged("fix-web"), 1)
        self.assertEqual(len(events(self.home, "fix-web")), 1)


if __name__ == "__main__":
    unittest.main()
