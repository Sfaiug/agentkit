"""The owner's unsent text reads needs you over a Stop on background work.

A seat that ended its turn on background work still in flight keeps its composer
open, so a line typed there is not sent. Its hook fact reads `working`, but his
own unsent text is his, as at a quiet prompt: `needs you` with `unsent: <text>`.
While a client is attached the draft is his typing, and with an empty composer
the background wait still reads `working`. Offline: a temporary HOME, fake hook
records and fake pane text; never a real seat, tmux or ~/.agentkit.
"""

import json
import os
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
DRAFT = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8", errors="replace")
TEXT = "Fix the login redirect"


class DraftOverBackground(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        self.attached = False
        self.pane = DRAFT
        config.save_session(self.cfg, SEAT, "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        listed = lambda *_a, **_k: [self.seat]
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text",
                                              side_effect=lambda *_a, **_k: self.pane))

    @property
    def seat(self):
        return {"name": SEAT, "repo": self.repo, "path": self.repo, "created": NOW - 86400,
                "attached": self.attached, "exited": False, "legacy": False,
                "resumable": False}

    def fact(self, event, kind="", at=NOW - 60):
        config.hook_facts_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "event": event, "kind": kind, "text": "", "at": at}))

    def decide(self):
        harness, live = watch.look_at(self.seat, cfg=self.cfg)
        found = watch.session_state(SEAT, NOW, session=self.seat, cfg=self.cfg,
                                    live=live, harness=harness,
                                    auth_out={}, gh_out={}, token_out={}, previous={})
        return found["word"], found["reason"]

    def test_background_stop_with_draft_and_nobody_attached_is_needs_you_unsent(self):
        self.fact("Stop", kind="background")
        self.assertEqual(self.decide(), ("needs you", f"unsent: {TEXT}"))

    def test_background_stop_with_draft_and_client_attached_is_working(self):
        self.fact("Stop", kind="background")
        self.attached = True
        self.assertEqual(self.decide()[0], "working")

    def test_background_stop_with_empty_composer_is_working(self):
        self.fact("Stop", kind="background")
        self.pane = PROMPT
        self.assertEqual(self.decide()[0], "working")


if __name__ == "__main__":
    unittest.main()
