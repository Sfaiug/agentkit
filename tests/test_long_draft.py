"""ak never types into, or moves, a seat whose composer holds the owner's text.

The draft rule reads the pane's last rows only, so a draft taller than its window puts the
composer's prompt row above it, and the seat reads `at_prompt`.  What acts on that word --
a line typed into the seat, an account move that reopens its pane -- reads the composer
itself first.  Offline: the claude captures with more lines typed into the composer; never
a real seat, pane or ~/.claude.
"""

import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, watch

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
    def at_prompt(self, pane):
        with patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value=pane), \
                patch.object(watch, "live_state",
                             return_value={"state": "at_prompt", "authority": "screen"}), \
                patch.object(watch, "_turn_in_flight", return_value=(False, None)):
            return watch.at_prompt({"name": SEAT}, cfg=self.cfg)

    def test_a_seat_holding_a_draft_taller_than_the_rule_s_window_is_never_typed_into(self):
        pane = taller(DRAFT, 8)
        found = watch.classify("claude", watch.pane_tail(pane), STOPPED, None, {}, NOW)
        self.assertEqual(found["state"], "at_prompt")          # the rule's window misses it
        self.assertFalse(self.at_prompt(pane))
        self.assertTrue(self.at_prompt(PROMPT))                # an empty composer takes a line

    def test_a_seat_holding_one_is_never_moved_to_another_account(self):
        config.save_session(self.cfg, SEAT, "opus", ["opus"], {"cwd": str(self.root)})
        provider = config.model(self.cfg, "opus")["provider"]
        with patch.object(config, "accounts",
                          side_effect=AssertionError("it went on to move the seat")):
            self.assertTrue(watch.seat_account(self.cfg, {"name": SEAT}, "claude", provider,
                                               taller(DRAFT, 8), False, lambda _: None))

    def test_text_typed_after_a_faint_reset_is_still_the_owner_s(self):
        # an empty prompt row with faint padding, then a row that resets and holds typed text
        pane = (FIX / "claude-suggestion-pane.txt").read_text(encoding="utf-8", errors="replace")
        shown = "\x1b[39m❯\xa0\x1b[7m \x1b[0m"
        self.assertIn(shown, pane)
        pane = pane.replace(shown, "\x1b[39m❯ \x1b[2m \n\x1b[0m  fix the parser")
        self.assertEqual(watch.composer_draft("claude", pane), "fixtheparser")


if __name__ == "__main__":
    unittest.main()
