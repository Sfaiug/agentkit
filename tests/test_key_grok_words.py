"""A Grok Build seat its hooks have said nothing about yet takes its word from its screen.

adapters/grokbuild.toml gives grok's hooks the say over every state, but until one fires -- a
seat just opened, a hook that never ran -- the screen rules there read the seat, and every place
that names a seat (the menu, its bar, `ak orch list`) says the word they give: needs you,
working or idle.  Each case here is a fresh grok seat whose pane shows one capture of a real
Grok Build screen from tests/fixtures, with no hook fact; `ak orch why` names the word and the
rule that read it.  Typed text never sent is no word of its own, and neither are a login's
expiry words: whether a login is out is the auth verb's answer, never the pane's.
"""

import itertools
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GrokWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.names = (f"acme-{n}" for n in itertools.count(1))

    def assertReads(self, word, table):
        """Each screen of `table`, alone on a grok seat, reads `word` by its rule."""
        for screen, rule in table.items():
            with self.subTest(screen=screen):
                name = next(self.names)
                Seat(self.home, name, model="grok", screen=screen)
                done = self.home.ak("orch", "why", name)
                self.assertEqual(done.code, 0, done.err)
                lines = done.out.splitlines()
                self.assertEqual(lines[:1], [f"{name}  {word}"], done.out)
                self.assertIn(f"  authority: screen  rule: {rule}", lines, done.out)

    def test_a_trust_dialog_or_a_permission_or_question_card_needs_you(self):
        self.assertReads("needs you", {
            "grok-dialog-pane.txt": "asking.trust",
            "grokbuild-permission-pane.txt": "asking.permission",
            "grokbuild-permission-narrow-pane.txt": "asking.permission",
            "grokbuild-permission-parked-pane.txt": "asking.permission",
            "grokbuild-question-pane.txt": "asking.question",
            "grokbuild-question-parked-pane.txt": "asking.question",
        })

    def test_a_turn_in_flight_or_compacting_is_working(self):
        # an answered question's card is gone while its spinner is still drawn
        self.assertReads("working", {
            "grok-working-pane.txt": "working.turn",
            "grokbuild-compacting-pane.txt": "working.turn",
            "grokbuild-question-answered-pane.txt": "working.turn",
            "grok-title-working-pane.txt": "working.turn",
            "grok-title-working-accepted-pane.txt": "working.turn",
            "grok-title-working-composed-pane.txt": "working.turn",
        })

    def test_an_empty_composer_is_idle_whatever_is_drawn_above_it(self):
        # a line taller than the box scrolls inside it, owner words or not, at any height
        self.assertReads("idle", {
            "grok-prompt-pane.txt": "prompt.composer",
            "grokbuild-background-pane.txt": "prompt.composer",
            "grokbuild-interrupted-pane.txt": "prompt.composer",
            "grok-tall-line-pane.txt": "prompt.composer",
            "grok-tall-line-and-owner-words-pane.txt": "prompt.composer",
            "grok-40-rows-tall-line-pane.txt": "prompt.composer",
            "grok-40-rows-tall-line-and-owner-words-pane.txt": "prompt.composer",
            "grok-50-rows-tall-line-pane.txt": "prompt.composer",
            "grok-50-rows-tall-line-and-owner-words-pane.txt": "prompt.composer",
            "grok-title-accepted-pane.txt": "prompt.composer",
            "grok-title-auto-pane.txt": "prompt.composer",
            "grok-title-idle-pane.txt": "prompt.composer",
            "grok-suggestion-pane.txt": "prompt.composer",
        })

    def test_the_last_prompt_suggested_faint_in_the_box_is_idle_by_its_own_rule(self):
        self.assertReads("idle", {"grokbuild-suggestion-pane.txt": "prompt.suggestion"})

    def test_a_login_expired_screen_with_its_composer_is_still_idle(self):
        self.assertReads("idle", {"grok-auth-pane.txt": "prompt.composer"})

    def test_text_typed_and_never_sent_is_idle_by_the_draft_rule(self):
        # under the first Esc's hint, under a slash command's dropdown, over a suggestion
        self.assertReads("idle", {
            "grok-draft-pane.txt": "prompt.draft",
            "grok-title-composed-pane.txt": "prompt.draft",
            "grokbuild-esc-clear-pane.txt": "prompt.draft",
            "grokbuild-slash-pane.txt": "draft.dropdown",
            "grokbuild-suggestion-typed-pane.txt": "prompt.draft",
        })


if __name__ == "__main__":
    unittest.main()
