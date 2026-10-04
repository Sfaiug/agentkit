"""A ruled composer is the box between its own rules, and what is typed in it is the owner's.

Claude Code draws its composer between two rules and puts a wrapped or multi-line draft on rows
under the prompt row.  Those rows are the draft, even one that reads like a rule (`---`), and a
seat whose composer holds any of it is never typed into.  The screens are a real 2.1.289
capture with invented names (tests/fixtures/claude-multiline-draft-pane.txt) and the empty
prompt capture with drafts written into it.
"""

import json
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
MULTILINE = (FIX / "claude-multiline-draft-pane.txt").read_text(encoding="utf-8")
STOPPED = {"event": "Stop", "kind": "", "at": NOW - 60}


def drafted(text):
    """The empty prompt capture with that typed into its composer."""
    return PROMPT.replace("❯ \n", "❯ " + text + "\n")


class ComposerBox(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        config.hook_facts_path(SEAT).write_text(json.dumps(STOPPED))

    def looked(self, pane):
        """(the seat's word, free to type into, keys a hand-back sent) on that screen."""
        live = watch.live_state({"name": SEAT}, "claude", pane=pane, cfg=self.cfg)
        word = watch.session_state(SEAT, NOW, session={"name": SEAT, "attached": False},
                                   cfg=self.cfg, records=[], live=live, harness="claude",
                                   auth_out={}, gh_out={}, token_out={}, previous={})["word"]
        keys = []
        with patch.object(watch, "pane_text", return_value=pane), \
                patch.object(orch, "tmux_out", side_effect=lambda *a, **_kw: keys.append(a)
                             or (0, "")):
            free = watch.at_prompt({"name": SEAT}, cfg=self.cfg)
            watch.type_at_prompt({"name": SEAT}, "The acme tests passed.", lambda _: None,
                                 cfg=self.cfg)
        return word, free, keys

    def test_a_draft_over_several_rows_is_the_owners(self):
        self.assertEqual(watch.screen_state("claude", watch.pane_tail(MULTILINE)),
                         ("draft", "prompt.draft", "Fix the acme login redirect, then run its tests"))
        self.assertEqual(watch.composer_draft("claude", MULTILINE),
                         "Fixtheacmeloginredirect,thenrunitstests")
        self.assertEqual(self.looked(MULTILINE), ("needs you", False, []))

    def test_rows_that_read_like_a_rule_are_still_the_draft(self):
        for text, said in (("Fix the login\n  redirect", "Fix the login redirect"),
                           ("\n  Fix the login redirect", "Fix the login redirect"),
                           ("\n  ---", "---"),
                           ("\n  ---\n  and the rest", "--- and the rest"),
                           ("Notes\n  " + "─" * 12, "Notes " + "─" * 12)):
            with self.subTest(text=text):
                pane = drafted(text)
                self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane)),
                                 ("draft", "prompt.draft", said))
                self.assertEqual(watch.composer_draft("claude", pane), said.replace(" ", ""))
                self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_a_draft_longer_than_the_tail_is_read_whole(self):
        """Thirteen rows push the box's top rule above the last 15 rows; the pane still has it."""
        rows = [f"step {n} of the acme migration" for n in range(1, 14)]
        pane = drafted("\n  ".join(rows))
        self.assertTrue(watch.pane_tail(pane).startswith("❯"))     # its top rule cut off
        self.assertEqual(watch.composer_draft("claude", pane), "".join(rows).replace(" ", ""))
        self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_a_box_whose_top_left_the_screen_is_never_typed_into(self):
        """A draft taller than the pane: no box to read, so the seat is not free."""
        rows = [f"step {n} of the acme migration" for n in range(1, 60)]
        pane = drafted("\n  ".join(rows))
        cut = pane.splitlines()
        top = max(at for at, row in enumerate(cut) if row.startswith("❯"))
        pane = "\n".join(cut[top + 1:]) + "\n"
        self.assertIsNone(watch.composer_draft("claude", pane))
        self.assertEqual(self.looked(pane)[1:], (False, []))

    def test_an_empty_composer_is_still_free(self):
        self.assertEqual(watch.composer_draft("claude", PROMPT), "")
        self.assertEqual(self.looked(PROMPT)[1:], (True, [
            ("send-keys", "-t", f"={SEAT}:", "-l", "The acme tests passed."),
            ("send-keys", "-t", f"={SEAT}:", "Enter")]))

    def test_typed_text_closes_the_seat_whatever_the_rules_said(self):
        with patch.object(watch, "screen_state",
                          return_value=("at_prompt", "prompt.composer", "")):
            self.assertEqual(self.looked(drafted("Fix the login"))[1:], (False, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
