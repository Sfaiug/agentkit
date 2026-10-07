"""A seat whose question was answered reads `working` until its turn's Stop.

Claude Code reports a question going up (`Notification/permission_prompt`, AskUserQuestion
included) and nothing when it comes down, and 2.1.289 no longer says `esc to interrupt` while a
turn runs, so its screen shows the composer mid-turn.  hooks/seat-state.sh and
hooks/orchestrator-stop.sh run as the harness runs them, on their own JSON on stdin, in a
temporary HOME; the screens are real captures with invented names
(tests/fixtures/claude-working-after-question-pane.txt).
"""

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
AFTER_QUESTION = (FIX / "claude-working-after-question-pane.txt").read_text(encoding="utf-8")
QUESTION = (FIX / "claude-question-pane.txt").read_text(encoding="utf-8")
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
PERMISSION = (FIX / "claude-dialog-pane.txt").read_text(encoding="utf-8")


class QuestionCameDown(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        home = self.root / ".agentkit"
        home.mkdir()
        (home / "state").symlink_to(config.STATE)

    def hook(self, event, script="seat-state.sh", **payload):
        """One hook call the way the harness makes it; the seat's record as it stands after."""
        done = subprocess.run(
            ["bash", str(REPO / "hooks" / script)], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": event, **payload}),
            env={"PATH": os.environ["PATH"], "HOME": str(self.root), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator", "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.root / f".agentkit/state/hook-{SEAT}.json").read_text())

    def looked(self, pane, fact):
        live = watch.classify("claude", watch.pane_tail(pane), fact, None, {}, NOW)
        word = watch.session_state(SEAT, NOW, session={"name": SEAT, "attached": False},
                                   cfg=self.cfg, records=[], live=live, harness="claude",
                                   auth_out={}, gh_out={}, token_out={}, previous={})["word"]
        with patch.object(watch, "pane_text", return_value=pane), \
                patch.object(watch, "live_state", return_value=live):
            free = watch.at_prompt({"name": SEAT}, cfg=self.cfg)
        return word, free

    def test_an_answered_question_leaves_its_turn_working_and_closed_to_typing(self):
        self.hook("UserPromptSubmit", prompt="Pick a colour, then sleep.")
        fact = self.hook("Notification", notification_type="permission_prompt",
                         message="Claude needs your permission")
        self.assertEqual(self.looked(QUESTION, fact), ("needs you", False))
        self.assertEqual(self.looked(AFTER_QUESTION, fact), ("working", False))
        self.assertEqual(self.looked(PROMPT, fact), ("working", False))

    def test_a_question_the_screen_cannot_read_stays_a_question(self):
        """A dialog no rule matches is no composer: the hook's question stands."""
        self.hook("UserPromptSubmit", prompt="Build the parser.")
        fact = self.hook("Notification", notification_type="permission_prompt",
                         message="Claude needs your permission")
        unread = QUESTION.rstrip() + "\n Some control nobody knows\n"
        self.assertEqual(watch.screen_state("claude", watch.pane_tail(unread))[0], None)
        self.assertEqual(self.looked(unread, fact), ("needs you", False))

    def test_its_turn_ends_on_a_recorded_question_or_an_idle_prompt(self):
        self.hook("UserPromptSubmit", prompt="Which schema should acme use?")
        self.hook("Notification", notification_type="permission_prompt",
                  message="Claude needs your permission")
        fact = self.hook("Stop", script="orchestrator-stop.sh", background_tasks=[],
                         last_assistant_message="Which schema should acme use?")
        self.assertEqual(self.looked(PROMPT, fact)[0], "working")
        result = subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", "needs",
                                 "--session", SEAT, "Which schema should acme use?"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        fact = self.hook("Stop", script="orchestrator-stop.sh", background_tasks=[],
                         last_assistant_message="Which schema should acme use?")
        self.assertNotEqual(self.looked(PROMPT, fact)[0], "working")
        self.hook("UserPromptSubmit", prompt="The second one.")
        self.hook("Notification", notification_type="permission_prompt",
                  message="Claude needs your permission")
        fact = self.hook("Notification", notification_type="idle_prompt",
                         message="Claude is waiting for your input")
        self.assertEqual(self.looked(PROMPT, fact), ("needs you", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
