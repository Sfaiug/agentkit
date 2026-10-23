"""An Antigravity seat's screen alone says which word the seat has, by its adapter's rules.

agy installs no hooks, so what its screen shows is the whole of what ak knows about the seat:
its trust, sign-in, permission and question dialogs need the owner, a turn's `esc to cancel`
footer is working, and the empty `>` composer is idle whatever the footer beside it carries (a
bracketed model label, a background command, the hint one Ctrl-C draws, a narrow pane's bare
hint).  A screen no rule reads, a first run's terms page or the `/usage` panel, is working, never
a seat at its prompt that the owner would be sent to.  A line typed and never sent is idle, its
words the evidence and never the reason.  Every screen is a real agy capture shipped under tests/fixtures/, shown in a
seat with no hook fact, and `ak orch why` names the word and what decided it.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

DECIDED = re.compile(r"^  authority: (\S+)\s+rule: (\S+)\s*$", re.M)
REASON = re.compile(r"^  reason:\s+(.*?)\s*$", re.M)
EVIDENCE = re.compile(r"^  evidence:\s+(.*?)\s*$", re.M)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AntigravityWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # `gemini` is the shipped config's Antigravity model; agy's composer is a bare `>`
        cls.seat = Seat(cls.home, "acme", model="gemini", composer=">",
                        screen="antigravity-prompt-pane.txt")

    def why(self, screen):
        """(the first line, (authority, rule), reason, evidence) `ak orch why` says over that
        screen."""
        self.seat.show(f"antigravity-{screen}-pane.txt")
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        decided, reason = DECIDED.search(done.out), REASON.search(done.out)
        self.assertTrue(decided and reason, done.out)
        evidence = EVIDENCE.search(done.out)
        return (done.out.splitlines()[0], decided.groups(), reason.group(1),
                evidence and evidence.group(1))

    def assertReads(self, cases, word):
        for screen, decided in cases:
            with self.subTest(screen):
                first, by, *_said = self.why(screen)
                self.assertEqual(first, f"acme  {word}")
                self.assertEqual(by, decided)

    def test_a_dialog_or_the_sign_in_chooser_needs_you(self):
        self.assertReads([("dialog", ("screen", "asking.trust")),
                          ("permission", ("screen", "asking.permission")),
                          ("question", ("screen", "asking.question")),
                          ("signin", ("screen", "asking.signin"))], "needs you")

    def test_a_turn_or_a_screen_no_rule_reads_is_working(self):
        # nothing on a screen no rule reads says the seat is at its prompt, and only its screen
        # could say so
        self.assertReads([("working", ("screen", "working.cancel")),
                          ("terms-ctrl-c", ("default", "none")),
                          ("usage", ("default", "none"))], "working")

    def test_the_empty_composer_is_idle_whatever_its_footer_says(self):
        self.assertReads([(screen, ("screen", "prompt.composer"))
                          for screen in ("prompt", "background", "bracketed-label", "ctrl-c",
                                         "narrow")], "idle")

    def test_a_line_typed_and_not_sent_is_idle_and_says_its_words(self):
        for screen, rule, words in (
                ("draft", "draft.typed", "Please look at the failing test in the"),
                ("background-draft", "draft.typed", "draft while task runs"),
                # the slash-command chooser a typed `/` opens is the owner's line, no dialog
                ("chooser", "draft.chooser", "/us")):
            with self.subTest(screen):
                self.assertEqual(self.why(screen), ("acme  idle", ("screen", rule), "-", words))


if __name__ == "__main__":
    unittest.main()
