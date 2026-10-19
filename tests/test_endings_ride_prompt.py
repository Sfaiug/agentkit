"""A prompt that starts a seat's turn carries the endings still waiting for it, once.

Offline: the real prompt hook and run records, in a temporary HOME.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, handback, record

SEAT = "fix-api"
CONVERSATION = "acme-conversation"


class EndingsRidePrompt(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": CONVERSATION,
            "id_source": "launcher", "resumable": True})
        rules = config.seat_rulebook(SEAT)
        config.rulebook_path(SEAT).write_text(rules)
        config.update_session(SEAT, rulebook_sha=config.rulebook_digest(rules))

    def waiting(self, name, owner=SEAT, **extra):
        """An ending its seat was busy for: deferred by `hand_back`, typed by nobody yet."""
        return self.ended(name, owner=owner, state="fail", verdict="FAIL",
                          handback_pending=True, **extra)

    def hook(self, prompt="Add these posts to the queue."):
        result = subprocess.run(
            ["bash", str(REPO / "hooks/seat-state.sh")],
            input=json.dumps({"hook_event_name": "UserPromptSubmit",
                              "session_id": CONVERSATION, "prompt": prompt}),
            text=True, capture_output=True, timeout=30,
            env={"HOME": str(self.root), "PATH": os.environ["PATH"],
                 "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"})
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        if not result.stdout:
            return ""
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_the_owners_prompt_carries_every_waiting_ending_once(self):
        first, second = self.waiting("fix-parser"), self.waiting("fix-schema")
        context = self.hook()
        for run_dir in (first, second):
            self.assertIn(f"run {run_dir.name} finished FAIL", context)
            said = record.read_state(run_dir)
            self.assertTrue(handback.already_handed_back(said))
            self.assertNotIn("handback_pending", said)
        self.assertEqual(context.count("Decide the next step."), 2)
        self.assertEqual(self.hook(), "")

    def test_an_ending_being_typed_or_another_seats_stays_waiting(self):
        typing = self.waiting("fix-parser")
        entered = self.waiting("fix-schema", handback_typed={"line": "run fix-schema"})
        other = self.waiting("fix-billing", owner="acme-web")
        with handback.delivery_lock(typing):
            self.assertEqual(self.hook(), "")
        for run_dir in (typing, entered, other):
            self.assertTrue(record.read_state(run_dir)["handback_pending"])
        self.assertIn("run fix-parser finished FAIL", self.hook())

    def test_a_prompt_that_is_no_words_of_a_turn_leaves_them_waiting(self):
        run_dir = self.waiting("fix-parser")
        for prompt in ("/rename fix-api", "<task-notification>done</task-notification>"):
            with self.subTest(prompt=prompt):
                self.assertNotIn("fix-parser", self.hook(prompt))
                self.assertTrue(record.read_state(run_dir)["handback_pending"])


if __name__ == "__main__":
    unittest.main()
