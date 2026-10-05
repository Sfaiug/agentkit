"""A ruled composer is the box between its own rules, and what is typed in it is the owner's.

Claude Code draws its composer between two rules and puts a wrapped or multi-line draft on rows
under the prompt row.  Those rows are the draft, even one that reads like a rule (`---`), and a
seat whose composer holds any of it is never typed into.  The screens are a real 2.1.289
capture with invented names (tests/fixtures/claude-multiline-draft-pane.txt) and the empty
prompt capture with drafts written into it.  A draft taller than the whole pane has no box
on the screen to read, as before.
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

    def test_typed_rule_glyphs_and_prompt_marks_are_never_the_box(self):
        """The box's rules and prompt row start at the left edge; a draft's rows are indented."""
        rows = PROMPT.splitlines()
        top = max(at for at, row in enumerate(rows) if row.startswith("❯")) - 1
        rows[top] = "─" * 89 + f" {SEAT} ─"           # a renamed seat's top rule
        named = "\n".join(rows) + "\n"
        for pane, said in (
                (named.replace("❯\u00a0\n", "❯\u00a0\n  " + "─" * 89 + "\n"), "─" * 89),
                (drafted("Fix the login\n  ───\n  ❯"), "Fix the login ─── ❯")):
            with self.subTest(said=said[:20]):
                self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane)),
                                 ("draft", "prompt.draft", said))
                self.assertEqual(watch.composer_draft("claude", pane), said.replace(" ", ""))
                self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_a_draft_in_a_box_with_corners_is_the_owners(self):
        for top, bottom in (("╭", "╮"), ("┌", "┐")):
            closing = {"╭": ("╰", "╯"), "┌": ("└", "┘")}[top]
            pane = (f"⏺ Done.\n{top}{'─' * 30}{bottom}\n│ ❯ Fix the login         │\n"
                    f"{closing[0]}{'─' * 30}{closing[1]}\n"
                    "⏵⏵ bypass permissions on (shift+tab to cycle)\n")
            with self.subTest(corners=top + bottom):
                self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane))[0], "draft")
                self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_an_empty_row_in_a_box_with_corners_is_no_draft(self):
        """Its edges are chrome on every row: both readers agree the composer is empty."""
        for top, closing in (("╭╮", "╰╯"), ("┌┐", "└┘")):
            pane = (f"⏺ Done.\n{top[0]}{'─' * 30}{top[1]}\n│ ❯                         │\n"
                    f"│                           │\n{closing[0]}{'─' * 30}{closing[1]}\n"
                    "⏵⏵ bypass permissions on (shift+tab to cycle)\n")
            with self.subTest(corners=top):
                self.assertNotEqual(watch.screen_state("claude", watch.pane_tail(pane))[0],
                                    "draft")
                self.assertEqual(watch.composer_draft("claude", pane), "")
                self.assertEqual(self.looked(pane)[1], True)

    def test_a_typed_row_that_reads_like_a_queued_message_is_the_draft(self):
        """Queued messages sit under the composer; inside its box a row like one was typed."""
        typed = "› Message from @build-check: Ready. (ctrl+o to expand)"
        pane = drafted("\n  " + typed)
        self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane)),
                         ("draft", "prompt.draft", typed))
        self.assertEqual(watch.composer_draft("claude", pane), typed.replace(" ", ""))
        self.assertEqual(self.looked(pane), ("needs you", False, []))
        under = PROMPT.replace("\n  ⏵⏵", "\n" + typed + "\n  ⏵⏵", 1)
        self.assertNotEqual(under, PROMPT)
        self.assertEqual(watch.composer_draft("claude", under), "")

    def test_a_draft_longer_than_the_tail_is_read_whole(self):
        """Thirteen rows push the box's top rule above the last 15 rows; the pane still has it."""
        rows = [f"step {n} of the acme migration" for n in range(1, 14)]
        pane = drafted("\n  ".join(rows))
        self.assertTrue(watch.pane_tail(pane).startswith("❯"))     # its top rule cut off
        self.assertEqual(watch.composer_draft("claude", pane), "".join(rows).replace(" ", ""))
        self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_a_faint_suggestion_wrapped_over_rows_is_no_draft(self):
        """tmux writes SGR 2 once, on the first row; the second row carries it unwritten."""
        rows = drafted("\x1b[0;2mTry fixing the acme login redirect and running all of its"
                       "\n  tests again").splitlines()
        at = next(at for at, row in enumerate(rows) if row.endswith("tests again"))
        rows[at + 1] = "\x1b[0m" + rows[at + 1]          # the reset comes on the closing rule
        pane = "\n".join(rows) + "\n"
        self.assertNotEqual(watch.screen_state("claude", watch.pane_tail(pane))[0], "draft")
        self.assertEqual(watch.composer_draft("claude", pane), "")
        self.assertEqual(self.looked(pane)[1:2], (True,))

    def test_an_older_boxed_composer_holding_its_placeholder_is_free(self):
        pane = ('⎿ Done.\n╭──────────────────╮\n│ > Try "fix tests" │\n╰──────────────────╯\n'
                '⏵⏵ bypass permissions on (shift+tab to cycle)   ◯ 92% context left\n')
        self.assertEqual(self.looked(pane)[1], True)

    def test_an_empty_composer_is_still_free(self):
        self.assertEqual(watch.composer_draft("claude", PROMPT), "")
        self.assertEqual(self.looked(PROMPT)[1:], (True, [
            ("send-keys", "-t", f"={SEAT}:", "-l", "The acme tests passed."),
            ("send-keys", "-t", f"={SEAT}:", "Enter")]))



if __name__ == "__main__":
    unittest.main(verbosity=2)
