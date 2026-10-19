"""A prompt that starts a seat's turn carries the endings still waiting for it, once.

Offline: the real prompt hook and run records, in a temporary HOME.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from test_health_after_merge import PR, SEAT as MERGED_SEAT, HealthAfterMerge
from agentkit import config, handback, orch, record

SEAT = "fix-api"
CONVERSATION = "acme-conversation"
OPEN = "- [ ] the parser parses\n"     # a plan line the seat still owes


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

    def test_a_change_gone_live_rides_once_while_the_seat_owes_work(self):
        config.plan_path(SEAT).write_text(OPEN)
        live = self.ended("fix-parser", owner=SEAT, merged=True, live_at=9995, pr=PR)
        self.ended("fix-schema", owner=SEAT, merged=True, live_at=9995, pr=PR,
                   live_typed={"line": "run fix-schema", "seat": 100})
        context = self.hook()
        self.assertIn(f"run fix-parser is live: {PR}.", context)
        self.assertNotIn("fix-schema", context)                # its Enter is the tick's
        self.assertTrue(record.read_state(live)["live_notified"])
        self.assertEqual(self.hook(), "")

    def test_a_change_gone_live_whose_record_is_being_written_stays_the_ticks(self):
        config.plan_path(SEAT).write_text(OPEN)
        live = self.ended("fix-parser", owner=SEAT, merged=True, live_at=9995, pr=PR)
        # a seat's rename writes it under this lock alone, from the record it read before
        with record.recovery_lock(live):
            self.assertEqual(self.hook(), "")
        self.assertNotIn("live_notified", record.read_state(live))

    def test_a_change_gone_live_for_a_seat_owing_nothing_is_the_ticks_to_record(self):
        live = self.ended("fix-parser", owner=SEAT, merged=True, live_at=9995, pr=PR)
        self.assertEqual(self.hook(), "")
        self.assertNotIn("live_notified", record.read_state(live))

    def test_a_prompt_that_is_no_words_of_a_turn_leaves_them_waiting(self):
        run_dir = self.waiting("fix-parser")
        for prompt in ("/rename fix-api", "<task-notification>done</task-notification>"):
            with self.subTest(prompt=prompt):
                self.assertNotIn("fix-parser", self.hook(prompt))
                self.assertTrue(record.read_state(run_dir)["handback_pending"])



class TickLeavesWhatRode(HealthAfterMerge):
    def test_a_live_line_a_prompt_carried_first_is_never_typed(self):
        config.plan_path(MERGED_SEAT).write_text(OPEN)
        directory = self.merged(self.declare("exit 0"))
        seat, carried = self.rows[0], []
        # a prompt starts the seat's turn between the pass reading the run and typing its line
        with patch.object(orch, "find",
                          lambda name: carried.append(handback.riding(name)) or seat):
            self.tick()
        self.assertIn(f"run {directory.name} is live: {PR}.", "".join(carried))
        self.assertEqual(self.lines, [])
        self.assertTrue(record.read_state(directory)["live_notified"])


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the harness it builds on runs its tests from its own file."""
    suite = unittest.TestSuite()
    for case in (EndingsRidePrompt, TickLeavesWhatRode):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite


if __name__ == "__main__":
    unittest.main()
