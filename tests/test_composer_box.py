"""A ruled composer is the box between its own rules, and what is typed in it is the owner's.

Claude Code draws its composer between two rules and puts a wrapped or multi-line draft on rows
under the prompt row.  Those rows are the draft, even one that reads like a rule (`---`), and a
seat whose composer holds any of it is never typed into.  The screens are a real 2.1.289
capture with invented names (tests/fixtures/claude-multiline-draft-pane.txt) and the empty
prompt capture with drafts written into it.  The screen is read within the rows it always was
(a draft rule's eight, the tail's fifteen); a draft taller than those is the typing gate's to
refuse, as a composer it cannot read.
"""

import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
MULTILINE = (FIX / "claude-multiline-draft-pane.txt").read_text(encoding="utf-8")
STOPPED = {"event": "Stop", "kind": "", "at": NOW - 60}


def drafted(text, pane=PROMPT):
    """The empty prompt capture, or that screen, with that typed into its composer."""
    return pane.replace("❯ \n", "❯ " + text + "\n")


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
        keys, screen = [], [pane]

        def typed(*args, **_kw):
            keys.append(args)
            if args[-2] == "-l":    # the text lands in the composer, and its Enter takes it
                screen[0] = drafted(args[-1], screen[0])
            elif args[-1] == "Enter":
                screen[0] = pane
            return 0, ""

        with patch.object(watch, "pane_text", side_effect=lambda *_a: screen[0]), \
                patch.object(orch, "tmux_out", side_effect=typed):
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

    def test_a_prompt_mark_on_a_boxed_continuation_is_the_owners(self):
        for top, closing in (("╭╮", "╰╯"), ("┌┐", "└┘")):
            for mark in "❯›⟩":
                pane = (f"⏺ Done.\n{top[0]}{'─' * 30}{top[1]}\n"
                        f"│ ❯ Fix the login              │\n│   {mark}                          │\n"
                        f"{closing[0]}{'─' * 30}{closing[1]}\n"
                        "⏵⏵ bypass permissions on (shift+tab to cycle)\n")
                said = f"Fix the login {mark}"
                with self.subTest(corners=top, mark=mark):
                    self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane)),
                                     ("draft", "prompt.draft", said))
                    self.assertEqual(watch.composer_draft("claude", pane),
                                     said.replace(" ", ""))
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

    def test_a_faint_reset_on_a_blank_row_ends_the_faint(self):
        """A draft's empty line can carry the reset that ends a faint run: the bright text
        under it is the owner's."""
        pane = drafted("\x1b[2m\n\x1b[0m\n  Fix the login")
        self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane)),
                         ("draft", "prompt.draft", "Fix the login"))
        self.assertEqual(watch.composer_draft("claude", pane), "Fixthelogin")
        self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_a_tall_status_line_under_the_box_is_never_read_as_its_output(self):
        """Its top rule can fall out of the tail; the box is still found, and everything under
        its closing rule stays chrome for the stall, login and stuck readers."""
        rows = PROMPT.splitlines()
        closing = max(at for at, row in enumerate(rows) if row.startswith("─"))
        status = [f"  acme status {n}" for n in range(11)] + [
            "  Please run /login · API Error: 401 Invalid API key"]
        pane = "\n".join(rows[:closing + 1] + status + rows[closing + 1:]) + "\n"
        tail = watch.pane_tail(pane)
        self.assertFalse(tail.splitlines()[0].startswith("─"))     # its top rule cut off
        said = "\n".join(watch.content_lines("claude", tail))
        self.assertNotIn("API Error", said)
        self.assertNotIn("/login", said)

    def test_faint_turned_on_and_off_around_no_text_draws_nothing_faint(self):
        """A blank row's faint code carries on to the next row, where a reset ends it before
        any text: the bright draft there is the owner's, on the prompt row or under it."""
        for pane, said in (
                (PROMPT.replace("❯\u00a0\n", "\x1b[2m\n\x1b[0m❯\u00a0Fix the login\n"),
                 "Fix the login"),
                (drafted("Fix the login\n\x1b[2m\n\x1b[0m  and its tests"),
                 "Fix the login and its tests")):
            with self.subTest(said=said):
                self.assertEqual(watch.screen_state("claude", watch.pane_tail(pane)),
                                 ("draft", "prompt.draft", said))
                self.assertEqual(watch.composer_draft("claude", pane), said.replace(" ", ""))
                self.assertEqual(self.looked(pane), ("needs you", False, []))

    def test_older_output_far_above_is_never_the_composer_of_an_unruled_harness(self):
        """Only a ruled composer's box is read past the tail: elsewhere an older composer or
        prompt echo higher up is history, never the composer drawn now."""
        opencode = (FIX / "opencode-prompt-pane.txt").read_text(encoding="utf-8")
        old_box = opencode.replace('Ask anything… "What is the tech stack of this project?"',
                                   "Fix the old thing")
        output = "".join(f"  ⏺ step {n} done\n" for n in range(30))
        legacy = "▌ Ask Codex to do something\n⏎ send  ⌃T transcript\n"
        for harness, pane in (("opencode", old_box + output + opencode),
                              ("codex", "› Fix the old thing\n" + output + legacy)):
            with self.subTest(harness=harness):
                self.assertNotIn("Fixtheoldthing", watch.composer_draft(harness, pane) or "")

    def test_an_older_claude_box_above_newer_output_is_not_the_composer(self):
        old = "─" * 40 + "\n❯ Fix the old thing\n" + "─" * 40 + "\n"
        output = "".join(f"⏺ step {n} done\n" for n in range(20))
        legacy = ('╭──────────────────╮\n│ > Try "fix tests" │\n╰──────────────────╯\n'
                  "⏵⏵ bypass permissions on (shift+tab to cycle)\n")
        pane = old + output + legacy
        self.assertNotEqual(watch.screen_state("claude", watch.pane_tail(pane))[0], "draft")
        self.assertNotIn("Fixtheoldthing", watch.composer_draft("claude", pane) or "")
        self.assertEqual(self.looked(pane)[1], True)

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
