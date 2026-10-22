"""A Muse seat's screen alone gives its word, by the rule adapters/muse.toml names for it.

The owner reads one of four words for every seat, on every harness.  On a Muse seat the screen
is the authority for all but its asking: a spinner, or the status line's own words while a turn
is interrupted, compacted or steered, is a turn at work; an empty composer is a seat at rest,
whatever its tray, title or tall last line shows; a draft or the owner's own picker never
changes that word; and a chooser or an approval only the owner can answer needs them.  Muse's
own question tool fires no hook a screen could fake, so with no hook having said it asks, that
question matches no rule and the seat stays working.  Each screen is a real capture of Muse Code
shown in a seat's pane, and `ak orch why` says the word and the rule that gave it.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

# tests/fixtures/muse-<screen>-pane.txt: the rule that reads it
ASKING = {"approval": "asking.approval", "auth": "asking.picker", "dialog": "asking.picker"}
AT_WORK = {"compacting": "working.footer", "interrupting": "working.footer",
           "working": "working.interrupt", "steering": "working.interrupt",
           "tray-working": "working.interrupt", "question-answered": "working.interrupt",
           "title-working-composed": "working.interrupt",
           "title-working-refused": "working.interrupt"}
QUESTION = {"question": "none", "question-asked": "none", "question-review": "none"}
AT_REST = {"prompt": "prompt.composer", "autoreview-idle": "prompt.composer",
           "overrides-idle": "prompt.composer", "compacted": "prompt.composer",
           "question-escaped": "prompt.composer", "suggestion": "prompt.composer",
           "tall-line": "prompt.composer", "tall-line-and-owner-words": "prompt.composer",
           "title-before-turn-refused": "prompt.composer",
           "title-idle-refused": "prompt.composer",
           "placeholder": "prompt.suggestion", "tray-placeholder": "prompt.suggestion"}
UNSENT = {"draft": "prompt.draft", "draft-wrapped": "prompt.draft",
          "tray-draft": "prompt.draft", "title-idle-composed": "prompt.draft",
          "model-picker": "prompt.picker", "resume-picker": "prompt.picker",
          "title-resume": "prompt.picker"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseWords(unittest.TestCase):
    """One seat whose pane shows each screen in turn: a word is read from the screen as it is
    now, so nothing one screen leaves changes the next."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seat = Seat(cls.home, "acme", model="spark", screen="muse-prompt-pane.txt")

    def reads(self, screens, word):
        for screen, rule in screens.items():
            with self.subTest(screen=screen):
                self.seat.show(f"muse-{screen}-pane.txt")
                done = self.home.ak("orch", "why", "acme")
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(done.out.splitlines()[0], f"acme  {word}", done.out)
                said = re.search(r"\brule: (\S+)$", done.out, re.M)
                self.assertEqual(said and said.group(1), rule, done.out)

    def test_a_chooser_or_an_approval_on_its_screen_needs_the_owner(self):
        self.reads(ASKING, "needs you")

    def test_a_spinner_or_the_status_line_at_work_reads_working(self):
        self.reads(AT_WORK, "working")

    def test_its_own_question_with_no_hook_said_matches_no_rule_and_reads_working(self):
        self.reads(QUESTION, "working")

    def test_an_empty_composer_reads_idle_whatever_its_tray_or_title_shows(self):
        self.reads(AT_REST, "idle")

    def test_a_draft_or_the_owner_s_own_picker_leaves_the_seat_idle(self):
        self.reads(UNSENT, "idle")

    def test_a_spent_usage_window_over_an_empty_composer_reads_working(self):
        self.reads({"stall": "prompt.composer"}, "working")


if __name__ == "__main__":
    unittest.main()
