"""The owner's unsent text reads as a draft however many rows it takes.

The draft rule reads the pane's last rows only, so a draft taller than its window puts the
composer's prompt row above it, and the screen alone reads `at_prompt`: an account move,
the menu or idle compaction would take the seat for idle with his text in it.  `classify`
reads the composer whole before it answers `at_prompt`.  Offline: the claude draft capture
with more lines typed into its composer; never a real seat, pane or ~/.claude.
"""

import unittest

from test_v4n import REPO, Sandbox
from agentkit import watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
DRAFT = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8", errors="replace")
STOPPED = {"event": "Stop", "at": NOW - 60}


def taller(pane, rows):
    """That capture with `rows` more lines typed under the composer's first."""
    lines = pane.rstrip("\n").split("\n")
    at = next(n for n, line in enumerate(lines) if "Fix the login redirect" in line)
    typed = [f"  and step {n} of the plan" for n in range(rows)]
    return "\n".join(lines[:at + 1] + typed + lines[at + 1:]) + "\n"


class LongDraft(Sandbox):
    def test_a_draft_taller_than_the_rule_s_window_is_a_draft(self):
        pane = watch.pane_tail(taller(DRAFT, 8))
        self.assertNotEqual(watch.screen_state("claude", pane)[0], "draft")   # past the window
        live = watch.classify("claude", pane, STOPPED, None, {}, NOW)
        self.assertEqual((live["state"], live["authority"]), ("draft", "screen"))
        # ... and what the owner reads is his own text
        found = watch.session_state(SEAT, NOW, session={"name": SEAT, "attached": False},
                                    cfg=self.cfg, records=[], live=live, harness="claude",
                                    auth_out={}, gh_out={}, token_out={}, previous={})
        self.assertEqual(found["word"], "needs you")
        self.assertTrue(found["reason"].startswith(
            "unsent: Fix the login redirect and step 0 of the plan and step 1"), found["reason"])

    def test_a_screen_no_rule_reads_as_a_composer_is_no_draft(self):
        # an empty resume picker: its bright search field reads like text after a prompt mark
        picker = (FIX / "muse-title-resume-pane.txt").read_text(encoding="utf-8", errors="replace")
        found = watch.classify("muse", watch.pane_tail(picker), STOPPED, None, {}, NOW)
        self.assertNotEqual(found["state"], "draft")

    def test_a_short_draft_still_reads_by_its_rule(self):
        found = watch.classify("claude", watch.pane_tail(DRAFT), STOPPED, None, {}, NOW)
        self.assertEqual((found["state"], found["rule"]), ("draft", "prompt.draft"))

    def test_an_empty_composer_is_still_at_prompt(self):
        found = watch.classify("claude", watch.pane_tail(PROMPT), STOPPED, None, {}, NOW)
        self.assertEqual(found["state"], "at_prompt")


    def test_a_faint_suggestion_over_two_rows_is_no_draft(self):
        # faint set on the first row carries on to the next until reset: all of it is a
        # suggestion or placeholder, nothing the owner typed
        for harness, name, shown, ghost in (
                ("claude", "claude-suggestion-pane.txt", "\x1b[39m❯\xa0\x1b[7m \x1b[0m",
                 "\x1b[39m❯ \x1b[2mTry checking the\n  parser next\x1b[0m"),
                ("codex", "codex-suggestion-pane.txt",
                 "\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m",
                 "\x1b[1m›\x1b[0m \x1b[2mAsk Codex to\n  do anything\x1b[0m")):
            with self.subTest(harness=harness):
                pane = (FIX / name).read_text(encoding="utf-8", errors="replace")
                self.assertIn(shown, pane)
                found = watch.classify(harness, watch.pane_tail(pane.replace(shown, ghost)),
                                       {}, None, {}, NOW)
                self.assertEqual(found["state"], "at_prompt")

if __name__ == "__main__":
    unittest.main()
