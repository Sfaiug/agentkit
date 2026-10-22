"""Each captured OpenCode screen reads as the seat word adapters/opencode.toml's rules give it.

The owner reads one of four words for every seat on every screen ak draws, and an OpenCode
seat's comes off its pane alone whenever its plugin has reported nothing yet: the permission
dialog is him, a streaming turn and an error the tick types it back past are working, and the
composer at rest is idle.  `ak orch why` says which rule decided and on whose authority, so a
rewrite that reads the same captures another way shows here.  Black-box: each seat is a real
tmux pane showing a shipped capture (tests/fixtures/opencode-*-pane.txt), with no hook fact.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpencodeWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A seat each: what one seat's last word left in its record never reaches another's.
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def why(self, name, screen):
        """The seat's word and the why lines under it, by their labels."""
        Seat(self.home, name, model="mimo", screen=screen)
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        first, *rest = done.out.splitlines()
        fields = dict(re.findall(r"(\w+):\s+(.*?)\s*(?=\s\s\w+:|$)", "\n".join(rest), re.M))
        return first, fields

    def assertWhy(self, name, screen, word, authority, rule, reason=None):
        first, fields = self.why(name, screen)
        self.assertEqual(first, f"{name}  {word}")
        self.assertEqual((fields.get("authority"), fields.get("rule")), (authority, rule))
        if reason is not None:
            self.assertEqual(fields.get("reason"), reason)

    def test_the_permission_dialog_needs_you(self):
        self.assertWhy("acme", "opencode-dialog-pane.txt", "needs you", "screen",
                       "asking.permission")

    def test_a_streaming_turn_is_working(self):
        self.assertWhy("beta", "opencode-working-pane.txt", "working", "screen",
                       "working.interrupt", "-")

    def test_a_spent_window_at_the_prompt_is_working_and_retrying_on_its_status(self):
        self.assertWhy("gamma", "opencode-stall-pane.txt", "working", "screen",
                       "prompt.composer", "retrying: 429")

    def test_a_refused_key_at_the_prompt_is_working_and_retrying_on_the_error(self):
        first, fields = self.why("delta", "opencode-auth-pane.txt")
        self.assertEqual(first, "delta  working")
        self.assertEqual((fields.get("authority"), fields.get("rule")),
                         ("screen", "prompt.composer"))
        self.assertTrue(fields.get("reason", "").startswith("retrying: Error:"), fields)

    def test_the_composer_at_rest_is_idle(self):
        self.assertWhy("epsilon", "opencode-prompt-pane.txt", "idle", "screen",
                       "prompt.composer", "-")

    def test_a_typed_but_unsent_draft_is_idle_at_the_composer(self):
        self.assertWhy("zeta", "opencode-draft-sidebar-hidden-pane.txt", "idle", "screen",
                       "prompt.composer", "-")

    def test_a_draft_beside_the_getting_started_card_matches_no_rule_and_is_idle(self):
        self.assertWhy("eta", "opencode-draft-beside-card-pane.txt", "idle", "default", "none",
                       "-")


if __name__ == "__main__":
    unittest.main()
