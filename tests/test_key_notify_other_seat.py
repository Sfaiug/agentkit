"""`ak notify needs --session NAME` keeps and pages the question under NAME, with or without a
seat record behind it.

`--session` is for a caller speaking for a seat it is not in: the tick speaks so for the inbox
seat, which need have no record.  So a name no record holds still gets the question, its card
and the page, under that name and no other, and no record is made up for it; and a seat asking
for another name leaves its own question and card as they were.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, beside a seat of
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


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ForAnotherName(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def asked(self, seat, question):
        notice = state(self.home, f"notify-{seat}.json")
        self.assertIsNotNone(notice, f"no question kept for {seat}")
        self.assertEqual({key: notice.get(key) for key in ("session", "kind", "text")},
                         {"session": seat, "kind": "needs", "text": question})
        self.assertEqual(state(self.home, f"card-{seat}.json")["word"], "needs you")

    def test_a_name_no_record_holds_has_its_question_kept_carded_and_paged(self):
        with Sink(self.home) as sink:
            done = self.home.ak("notify", "needs", "Which branch?", "--session", "other")
            self.assertEqual(done.code, 0, done.err)
            sink.wait(1)
            self.assertEqual(sink.pages(), ["🙋 Needs you · other"])
        self.asked("other", "Which branch?")
        self.assertIsNone(state(self.home, "session-other.json"))

    def test_a_seat_asking_for_another_name_leaves_its_own_seat_unasked(self):
        Seat(self.home, "acme")
        with Sink(self.home) as sink:
            done = self.home.ak("notify", "needs", "Which schema?", "--session", "beta",
                                env={"AGENTKIT_SESSION": "acme"})
            self.assertEqual(done.code, 0, done.err)
            sink.wait(1)
            self.assertEqual(sink.pages(), ["🙋 Needs you · beta"])
        self.asked("beta", "Which schema?")
        self.assertIsNone(state(self.home, "notify-acme.json"))
        self.assertIsNone(state(self.home, "card-acme.json"))


if __name__ == "__main__":
    unittest.main()
