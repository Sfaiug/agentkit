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
from fixtures.akseat import FIXTURES, Seat

SIDEBAR = "opencode-prompt-beside-sidebar-pane.txt"     # 2.4.2 past its first turn, 240 columns


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

    def test_a_draft_beside_the_getting_started_card_is_idle_at_the_composer(self):
        self.assertWhy("eta", "opencode-draft-beside-card-pane.txt", "idle", "screen",
                       "prompt.composer", "-")

    def test_the_composer_at_rest_beside_the_sidebar_is_idle_at_the_composer(self):
        # 2.4.2 at 240 columns ends its footer on the sidebar's path: read by no rule, a seat
        # opened that wide took no line after its first turn (27 Nov 2026)
        self.assertWhy("theta", SIDEBAR, "idle", "screen", "prompt.composer", "-")

    def test_a_sidebar_path_behind_an_ellipsis_is_idle_at_the_composer(self):
        # one under the owner's home is shortened to open on the ellipsis, no `/` before it
        wide = (FIXTURES / SIDEBAR).read_text(encoding="utf-8")
        path = "/…/code/fix-api".ljust(38)
        self.assertIn(path, wide)
        self.assertWhy("iota", wide.replace(path, "…/acme-with-a-very-long-name-…/fix-api"),
                       "idle", "screen", "prompt.composer", "-")

    def test_a_spent_window_beside_the_sidebar_is_working_and_retrying_on_its_status(self):
        # the path after the key hints is no output newer than the error, nor the usage beside it
        wide = (FIXTURES / SIDEBAR).read_text(encoding="utf-8")
        spent, replies = re.subn(r"(?<=m)ok(\x1b\[[\d;]*m) {26}",
                                 r"Error: 429 Too Many Requests\1", wide)
        self.assertEqual(replies, 1)
        self.assertWhy("kappa", spent, "working", "screen", "prompt.composer", "retrying: 429")

    def test_a_reply_going_on_after_the_key_hints_is_idle_over_an_older_error(self):
        # the sidebar's path follows the hints on their row, and a footer read with it there
        # read this reply as chrome too: the spent window above it was retried
        status = "     Build · mimo-v2.6-pro · 166ms\n"
        stall = (FIXTURES / "opencode-stall-pane.txt").read_text(encoding="utf-8")
        later = ("\n  ┃\n  ┃  Show the shortcuts as aligned columns\n  ┃\n\n"
                 "     ctrl+p commands    /help\n\n" + status)
        self.assertWhy("lambda", stall.replace(status, status + later), "idle", "screen",
                       "prompt.composer", "-")

    def test_a_reply_on_a_background_of_its_own_is_idle_over_an_older_error(self):
        # a blank row's codes go on at the head of the row under it, so the reply's sets the
        # screen's background first, as a row beside the sidebar does, and it comes back to it
        # in cells a tail's rows are stripped of: cut as a sidebar, the reply was no output and
        # the spent window above it was retried
        status = "     Build · mimo-v2.6-pro · 166ms\n"
        stall = (FIXTURES / "opencode-stall-pane.txt").read_text(encoding="utf-8")
        row = "     \x1b[48;2;20;20;20m{:60}\x1b[49m  \n"
        later = ("\n  ┃\n  ┃  Show what changed\n  ┃\n\n" + row.format("")
                 + row.format("  1 file changed") + "\n" + status)
        self.assertWhy("mu", stall.replace(status, status + later), "idle", "screen",
                       "prompt.composer", "-")

    def test_a_spent_window_beside_tabs_down_the_left_is_working_and_retrying_on_its_status(self):
        # 2.4.2 can stand its tabs down the left, on the sidebar's background: every row sets
        # that first and leaves it for the screen's, and cut there, as one beside the sidebar
        # is, the seat showed no row at all
        tabs = "\x1b[48;2;20;20;20m" + " " * 42 + "\x1b[48;2;8;8;8m"
        stall = (FIXTURES / "opencode-stall-pane.txt").read_text(encoding="utf-8").splitlines()
        wide = max(map(len, stall))
        self.assertWhy("nu", "".join(f"{tabs}{row:{wide}}\n" for row in stall), "working",
                       "screen", "prompt.composer", "retrying: 429")


if __name__ == "__main__":
    unittest.main()
