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
        found = watch.classify("claude", pane, STOPPED, None, {}, NOW)
        self.assertEqual((found["state"], found["authority"]), ("draft", "screen"))

    def test_a_short_draft_still_reads_by_its_rule(self):
        found = watch.classify("claude", watch.pane_tail(DRAFT), STOPPED, None, {}, NOW)
        self.assertEqual((found["state"], found["rule"]), ("draft", "prompt.draft"))

    def test_an_empty_composer_is_still_at_prompt(self):
        found = watch.classify("claude", watch.pane_tail(PROMPT), STOPPED, None, {}, NOW)
        self.assertEqual(found["state"], "at_prompt")


if __name__ == "__main__":
    unittest.main()
