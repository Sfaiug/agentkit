"""`ak notify needs` takes a question only when it asks first: its "?" within 80 characters.

A seat's bar and its menu row show a question from its start and cut the rest, so a question
whose ask comes after its context reads as a status line, and the owner takes a seat asking
them something for one reporting.  A text whose "?" is missing or past its 80th character is
refused with exit 2 and a line saying how to ask, dry run or not, and nothing is recorded or
paged: the seat asks again, the right way round.  The count is of characters, not bytes, from
the first word, a run of spaces or line breaks counting as one, as the bar shows it; what is
kept is the text as written, its ends trimmed.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, before a seat of tests/fixtures/akseat.py, paging
tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

REFUSAL = ('ak notify: put the question first, its "?" within 80 characters: the status bar '
           "and the menu show a question's start; context goes after it")
CONTEXT_FIRST = ("Context first: the parser change touches three modules and the migration, "
                 "so which branch?")


def spaced(words):
    """`words` two-letter words asking at the last, spread over lines and runs of spaces: each
    word and the single space after it is three characters as the bar shows them."""
    return "\n   " + "  \n  ".join(["ab"] * words) + "?"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class QuestionShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        cls.state = cls.home.path / ".agentkit" / "state"
        Seat(cls.home, "fix-api")
        Seat(cls.home, "fix-web")

    def asked(self, text, *flags, seat="fix-api", env=None):
        return self.home.ak("notify", "needs", text, "--session", seat, *flags, env=env)

    def assertTaken(self, text):
        done = self.asked(text, "--dry-run")
        self.assertEqual(done.code, 0, done.err)
        self.assertNotIn(REFUSAL, done.err.splitlines())

    def assertRefused(self, text, *flags):
        done = self.asked(text, *flags)
        self.assertEqual(done.code, 2, done.err)
        self.assertIn(REFUSAL, done.err.splitlines())
        self.assertEqual(done.out, "")
        for kept in ("notify-fix-api.json", "card-fix-api.json"):
            self.assertFalse((self.state / kept).exists(), kept)
        outbox = (json.loads(path.read_text())
                  for path in (self.state / "notification-outbox").glob("*.json"))
        self.assertEqual([event for event in outbox if event.get("session") == "fix-api"], [])
        self.assertEqual(self.sink.requests, [])

    def test_context_before_the_ask_is_refused_and_nothing_is_recorded_or_paged(self):
        self.assertRefused(CONTEXT_FIRST)

    def test_a_text_that_asks_nothing_is_refused(self):
        self.assertRefused("no question here")

    def test_a_dry_run_is_refused_the_same_and_shows_no_card(self):
        self.assertRefused(CONTEXT_FIRST, "--dry-run")
        self.assertRefused("no question here", "--dry-run")

    def test_the_ask_may_end_on_the_80th_character_and_not_the_81st(self):
        self.assertTaken("x" * 79 + "? Context after it may run as long as it needs to.")
        self.assertRefused("x" * 80 + "?")

    def test_characters_count_not_bytes(self):
        self.assertTaken("é" * 79 + "?")
        self.assertRefused("é" * 80 + "?")

    def test_a_run_of_spaces_or_line_breaks_counts_once_and_leading_ones_not_at_all(self):
        self.assertGreater(spaced(26).index("?"), 80)
        self.assertTaken(spaced(26))        # its "?" is the 78th character as the bar shows it
        self.assertRefused(spaced(27))      # and here the 81st

    def test_a_question_that_asks_first_is_kept_as_written_its_ends_trimmed(self):
        text = "Which branch should the fix land on?  It touches\nthe parser."
        done = self.asked(f"\n  {text}\n", seat="fix-web", env={"AK_NOTIFY_SINK": "dry-run"})
        self.assertEqual(done.code, 0, done.err)
        notice = json.loads((self.state / "notify-fix-web.json").read_text())
        self.assertEqual((notice["kind"], notice["text"]), ("needs", text))


if __name__ == "__main__":
    unittest.main()
