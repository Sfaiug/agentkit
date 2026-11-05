"""A Claude Code draft taller than the rows its screen rules read is read as a draft.

On 5 Nov 2026 a seat holding the owner's long unsent message read as an empty prompt, and the
tick restarted it and lost the message: on Claude Code 2.1.318 a draft wrapped to seven rows,
or typed over six lines, had its prompt row above the eight rows the draft rule read.  Each
case is a real capture, on a seat whose turn has ended and that nobody is in.
Offline: the captures, a fake hook record and a sandboxed HOME.
"""

import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, watch

SEAT = "fix-api"
NOW = 1_800_000_000
ASKED = "and then also check how the columns on the monitor page line up with the helper "
# each capture, and its text as the seat's row says it is unsent: whole, or its first 160
DRAFTS = {"claude-tall-draft-rows-pane.txt": (ASKED * 2)[:160].rstrip(),
          "claude-tall-draft-lines-pane.txt": " ".join(
              [f"point {n} of what I want next" for n in range(1, 6)] + ["last point"])}


class TallDraft(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        config.hook_facts_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "event": "Stop", "kind": "", "text": "", "at": NOW}))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))

    def test_a_draft_taller_than_the_rules_rows_is_the_owners_unsent_text(self):
        seat = {"name": SEAT, "created": NOW - 86400, "attached": False, "exited": False}
        for name, text in DRAFTS.items():
            pane = (REPO / "tests/fixtures" / name).read_text(encoding="utf-8")
            with self.subTest(name), patch.object(watch, "pane_text", return_value=pane):
                harness, live = watch.look_at(seat, cfg=self.cfg, now=NOW)
                found = watch.session_state(SEAT, NOW, session=seat, cfg=self.cfg,
                                            live=live, harness=harness)
                self.assertEqual((live["state"], live["rule"], found.get("unsent")),
                                 ("draft", "prompt.draft", text))


if __name__ == "__main__":
    unittest.main()
