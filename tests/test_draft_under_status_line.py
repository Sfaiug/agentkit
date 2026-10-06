"""The owner's unsent text reads as a draft with a status line under the composer.

A Claude seat can draw the user's own `statusLine` between its composer's bottom rule and
the bypass footer, in whatever format he chose.  Text typed in the composer is still his
unsent draft -- `draft`, and `needs you` with `unsent: <text>` -- and the same screen with
an empty composer is still `at_prompt`.  Offline: the claude captures with invented status
lines spliced in above their footer; never a real seat, pane or ~/.claude.
"""

import unittest

from fixtures.sandbox import REPO, Sandbox
from agentkit import watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
DRAFT = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8", errors="replace")
TEXT = "Fix the login redirect"        # what sits typed in the draft capture's composer
# Status lines are the user's own command's output: no pattern names them.
STATUS = (
    "\x1b[32mdev@box\x1b[0m:~/code/acme | Opus 5.5 | ctx ░░░░░░░░░░ 0/1M (0%)",
    "acme main* · $0.42",
    "acme · fix-api\n[####      ] 40% · 3h left",
)
# ... and may start with a prompt mark, on its first line or a later one: still no composer,
# even over a line that reads like the harness's own chrome.
MARKED = ("❯ acme main*", "❯", "acme · fix-api\n› 40% · 3h left", "⟩ acme main*\n[####  ] 40%",
          "❯ acme main*\n? for shortcuts", "❯ acme\nbypass permissions on",
          "› acme\n● high · /effort")


def under_status(pane, status):
    """That capture with a status line drawn between its composer and its footer."""
    lines = pane.rstrip("\n").split("\n")
    at = next(n for n, line in enumerate(lines) if "bypass permissions on" in line)
    return "\n".join(lines[:at] + status.split("\n") + lines[at:]) + "\n"


class DraftUnderStatusLine(Sandbox):
    def read(self, pane):
        return watch.screen_state("claude", watch.pane_tail(pane))

    def test_typed_text_over_any_status_line_is_a_draft(self):
        for status in STATUS + MARKED:
            with self.subTest(status=status):
                self.assertEqual(self.read(under_status(DRAFT, status)),
                                 ("draft", "prompt.draft", TEXT))

    def test_an_empty_composer_over_the_same_status_line_is_at_prompt(self):
        for status in STATUS + MARKED:
            with self.subTest(status=status):
                self.assertEqual(self.read(under_status(PROMPT, status))[:2],
                                 ("at_prompt", "prompt.composer"))

    def test_the_draft_is_needs_you_unsent(self):
        live = watch.classify("claude", watch.pane_tail(under_status(DRAFT, STATUS[0])),
                              {"event": "Stop", "at": NOW - 60}, None, {}, NOW)
        found = watch.session_state(SEAT, NOW, session={"name": SEAT, "attached": False},
                                    cfg=self.cfg, records=[], live=live, harness="claude",
                                    auth_out={}, gh_out={}, token_out={}, previous={})
        self.assertEqual((found["word"], found["reason"]), ("needs you", f"unsent: {TEXT}"))

    def test_a_picker_cursor_over_a_status_line_is_no_draft(self):
        # Under a cursor sits another option or the status line: never the composer's rule,
        # and a status line right on the footer is no composer even with a prompt mark.
        footer = "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents\n"
        for picker in ("❯ 1. Yes\n  2. No\n", "  1. Yes\n❯ 2. No\n"):
            for status in STATUS + MARKED:
                with self.subTest(picker=picker, status=status):
                    pane = under_status("Do you want to proceed?\n" + picker + footer, status)
                    self.assertNotEqual(self.read(pane)[0], "draft")


if __name__ == "__main__":
    unittest.main()
