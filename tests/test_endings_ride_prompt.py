"""A prompt that starts a seat's turn carries the run notices still waiting for it, once.

Offline: the real prompt hook and run records, in a temporary HOME.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, handback, orch, record, watch

SEAT = "fix-api"
CONVERSATION = "acme-conversation"
PR = "https://github.com/acme/widget/pull/7"


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

    def live(self, name, owner=SEAT, **extra):
        return self.ended(name, owner=owner, **{
            "merged": True, "live_at": 9995, "pr": PR,
            "handed_back": 9991, "reported": True, **extra})

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

    def test_waiting_live_notices_ride_once_and_a_tick_with_an_old_snapshot_types_none(self):
        config.plan_path(SEAT).write_text("- [ ] the parser is live\n")
        first = self.live("run-live")
        second = self.live("run-both", handback_pending=True, handed_back=None, reported=False)
        snapshots = [(directory, record.read_state(directory)) for directory in (first, second)]
        context = self.hook()
        self.assertIn("run run-both finished PASS", context)
        for directory, stale in snapshots:
            self.assertIn(f"run {directory.name} is live: {PR}.", context)
            said = record.read_state(directory)
            self.assertEqual(said["live_at"], stale["live_at"])
            self.assertTrue(said["live_notified"])
            with patch.object(watch, "after_merge_live", return_value=True), \
                    patch.object(orch, "find", return_value={"name": SEAT}), \
                    patch.object(watch, "type_at_prompt", return_value=True) as typed:
                watch.after_merge_health(directory, stale, "acme/widget", "a" * 40,
                                         PR, 10000, False, lambda _line: None, {})
            typed.assert_not_called()
        self.assertEqual(self.hook(), "")

    def test_live_notices_being_typed_or_another_seats_stay_waiting(self):
        config.plan_path(SEAT).write_text("- [ ] the parser is live\n")
        typing = self.live("run-typing")
        entered = self.live("run-entered", live_typed={"line": "run run-entered is live"})
        other = self.live("run-other", owner="acme-web")
        self.live("run-told", live_notified=9996)
        self.live("run-unmerged", merged=False)
        self.live("run-unproven", live_at=None)
        with handback.delivery_lock(typing):
            self.assertEqual(self.hook(), "")
        for directory in (typing, entered, other):
            self.assertNotIn("live_notified", record.read_state(directory))
        self.assertIn("run run-typing is live:", self.hook())
        for directory in (entered, other):
            self.assertNotIn("live_notified", record.read_state(directory))

    def test_a_live_notice_does_not_ride_when_the_seat_owes_nothing(self):
        directory = self.live("run-live")
        self.assertEqual(self.hook(), "")
        self.assertNotIn("live_notified", record.read_state(directory))

    def test_a_prompt_during_live_typing_leaves_the_delivery_to_the_tick(self):
        config.plan_path(SEAT).write_text("- [ ] the parser is live\n")
        directory = self.live("run-live")

        def send(_seat, _line, _log, **_kw):
            self.assertEqual(self.hook(), "")
            self.assertNotIn("live_notified", record.read_state(directory))
            return True

        with patch.object(watch, "after_merge_live", return_value=True), \
                patch.object(orch, "find", return_value={"name": SEAT}), \
                patch.object(watch, "type_at_prompt", side_effect=send) as typed:
            watch.after_merge_health(directory, record.read_state(directory), "acme/widget",
                                     "a" * 40, PR, 10000, False, lambda _line: None, {})
        typed.assert_called_once()
        self.assertTrue(record.read_state(directory)["live_notified"])
        self.assertEqual(self.hook(), "")

    def test_a_prompt_that_is_no_words_of_a_turn_leaves_them_waiting(self):
        run_dir = self.waiting("fix-parser")
        config.plan_path(SEAT).write_text("- [ ] the parser is live\n")
        live = self.live("run-live")
        for prompt in ("/rename fix-api", "<task-notification>done</task-notification>"):
            with self.subTest(prompt=prompt):
                self.assertNotIn("fix-parser", self.hook(prompt))
                self.assertTrue(record.read_state(run_dir)["handback_pending"])
                self.assertNotIn("live_notified", record.read_state(live))


if __name__ == "__main__":
    unittest.main()
