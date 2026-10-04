"""A queued session message never hides a Claude question or becomes an owner's draft.

Replay panes with invented names, fake runs and a temporary HOME; no real seats or hooks.
"""

import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
QUESTION = (FIX / "claude-question-with-message-pane.txt").read_text(encoding="utf-8")
DIALOG, MESSAGE = QUESTION.rstrip().rsplit("\n", 1)
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
DRAFT = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8")
PREVIEW = (FIX / "claude-question-preview-pane.txt").read_text(encoding="utf-8")
NOTES = (FIX / "claude-question-notes-pane.txt").read_text(encoding="utf-8")


class QuestionWithMessageUnder(Sandbox):
    def classify(self, pane, fact=None):
        return watch.classify("claude", watch.pane_tail(pane), fact or {}, None, {}, NOW)

    def test_dialog_with_queued_message_is_asking_and_needs_you_over_runs(self):
        for fact in ({}, {"event": "Notification", "kind": "permission_prompt",
                          "text": "Choose a change", "at": NOW - 7200}):
            for attached in (False, True):
                with self.subTest(fact=fact, attached=attached):
                    live = self.classify(QUESTION, fact)
                    self.assertEqual(live["state"], "asking")
                    records = [(self.root / "run", {"state": "running",
                                "launched_session": SEAT, "started_at": NOW - 3600})]
                    found = watch.session_state(
                        SEAT, NOW, session={"name": SEAT, "attached": attached},
                        cfg=self.cfg, records=records, live=live, harness="claude",
                        auth_out={}, gh_out={}, token_out={}, previous={})
                    self.assertEqual(found["word"], "needs you")

    def test_dialog_alone_is_asking_from_its_screen(self):
        live = self.classify(DIALOG)
        self.assertEqual(live["state"], "asking")
        self.assertEqual(live["authority"], "screen")

    def test_multi_question_and_edit_hint_footers_are_asking(self):
        single = "Enter to select · ↑/↓ to navigate · Esc to cancel"
        footers = (
            "Enter to select · Tab/Arrow keys to navigate · Esc to cancel",
            "Enter to select · ↑/↓ to navigate · ctrl+g to edit in vim · Esc to cancel",
            "Enter to select · Tab/Arrow keys to navigate · ctrl+g to edit in vim · Esc to cancel",
        )
        idle = {"event": "Notification", "kind": "idle_prompt", "at": NOW - 60}
        for footer in footers:
            pane = DIALOG.replace(single, footer)
            for queued in ("", MESSAGE):
                for fact in ({}, idle):
                    with self.subTest(footer=footer, queued=bool(queued),
                                      fact=fact.get("kind", "none")):
                        live = self.classify(pane + queued, fact)
                        self.assertEqual(live["state"], "asking")
                        self.assertEqual(live["authority"], "screen")

    def test_question_with_previews_is_asking_whatever_its_hooks_last_said(self):
        """Claude 2.1.289 adds `n to add notes` to a question whose options have previews, and
        `ctrl+g to edit in <editor>` beside it while a note is open.

        Nothing types into it, however the hooks last read: an Enter there picks an answer.
        """
        for pane, fact in ((pane, fact) for pane in (PREVIEW, NOTES) for fact in ({}, {"event": "Notification", "kind": "permission_prompt", "at": NOW - 60},
                     {"event": "Notification", "kind": "idle_prompt", "at": NOW - 5},
                     {"event": "Stop", "kind": "", "at": NOW - 5})):
            with self.subTest(note=pane is NOTES, fact=fact.get("kind", fact.get("event", "none"))):
                live = self.classify(pane, fact)
                self.assertEqual(live["state"], "asking")
                with patch.object(watch, "pane_text", return_value=pane), \
                        patch.object(watch, "live_state", return_value=live):
                    self.assertFalse(watch.at_prompt({"name": SEAT}, cfg=self.cfg))
                found = watch.session_state(
                    SEAT, NOW, session={"name": SEAT, "attached": False}, cfg=self.cfg,
                    records=[], live=live, harness="claude", auth_out={}, gh_out={},
                    token_out={}, previous={})
                self.assertEqual(found["word"], "needs you")

    def test_message_under_empty_composer_is_not_a_draft(self):
        self.assertEqual(self.classify(PROMPT + MESSAGE)["state"], "at_prompt")

    def test_typed_draft_stays_a_draft_with_or_without_queued_message(self):
        for queued in ("", MESSAGE):
            with self.subTest(queued=bool(queued)):
                live = self.classify(DRAFT + queued)
                self.assertEqual(live["state"], "draft")
                self.assertEqual(live["evidence"], "Fix the login redirect")

    def test_owner_can_type_text_that_looks_like_a_message(self):
        text = "Message from @build-check: Ready. (ctrl+o to expand)"
        pane = DRAFT.replace("Fix the login redirect", text)
        self.assertEqual(self.classify(pane)["evidence"], text)
        self.assertEqual(self.classify(pane)["state"], "draft")

    def test_dialog_in_transcript_does_not_keep_old_asking_hook(self):
        fact = {"event": "Notification", "kind": "permission_prompt", "at": NOW - 60}
        for queued in ("", MESSAGE):
            with self.subTest(queued=bool(queued)):
                self.assertEqual(self.classify(DIALOG + "\n" + PROMPT + queued, fact)["state"],
                                 "at_prompt")


if __name__ == "__main__":
    unittest.main()
