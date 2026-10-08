"""Run notices share ak tell's bound; the full result and plan keep every follow-up.

Offline: a temporary HOME and a fake seat whose composer shows only a prefix of an
oversized line. The real confirmed send must get its Enter and leave no unsent notice.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import Sandbox
from agentkit import config, orch, plan, record, run, tell, watch, worktrees


class RunNotice(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_RUN_ROLE": "orchestrator",
            "AK_NOTIFY_SINK": "dry-run"}))
        self.seat = {"name": "fix-api", "created": 100, "legacy": False}
        config.save_session(self.cfg, "fix-api", "opus", ["astra"], {
            "cwd": str(self.root), "created": 100, "conversation": "fixture-thread"})
        self.composer, self.sent, self.keys, self.logs = "", [], [], []
        self.visible = tell.longest(self.cfg)
        self.stack.enter_context(patch.object(orch, "find", return_value=self.seat))
        self.stack.enter_context(patch.object(orch, "watching", return_value=True))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "at_prompt", return_value=True))
        self.stack.enter_context(patch.object(watch, "pane_unread", return_value=False))
        self.stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda *_a, **_kw:
                                             "❯ " + self.composer[:self.visible] + "\n"))
        self.stack.enter_context(patch.object(watch, "seat_model", return_value=("claude", "acme")))
        self.stack.enter_context(patch.object(worktrees, "_drop_told"))
        self.elapsed = 0
        clock = Clock(lambda gap: setattr(self, "elapsed", self.elapsed + gap))
        clock.monotonic = lambda: self.elapsed
        self.stack.enter_context(patch.object(watch, "time", clock))

    def tmux(self, *args, **_kw):
        self.assertEqual(args[0], "send-keys")
        self.keys.append(args[-1])
        if "-l" in args:
            self.composer += args[-1]
        elif args[-1] == "Enter":
            self.sent.append(self.composer)
            self.composer = ""
        return 0, ""

    def result(self, name="fix-api", **extra):
        directory = self.ended(name, owner="fix-api", **{
            "merged": True, "pr": "https://github.com/acme/widget/pull/7",
            "rounds": 3, "round_summaries": [], "findings": "", "branch": "ak/fix-api",
            "base_sha": "a" * 40, "worktree": str(self.root), **extra})
        state = record.read_state(directory)
        with patch.object(run, "git", return_value="(fixture diff)"):
            run.write_result(directory, state, [])
        return directory, state

    def followups(self, count, **extra):
        items = [f"api.py:{i + 1} - defect {i + 1}: " + "complete evidence " * 25
                 for i in range(count)]
        directory, state = self.result(followups=items, **extra)
        entries = [{"outcome": "Fix " + item} for item in items]
        plan.path("fix-api").write_text("\n".join(entry["outcome"] for entry in entries))
        run.followups_handed(directory, state, {"followup_plan": entries, "followup_runs": []})
        return directory, state

    def test_two_long_followups_get_enter_and_leave_nothing_pending(self):
        directory, state = self.followups(2)
        # The original notice is larger than the whole composer, even without its result.
        self.assertGreater(len(run.planned_followups(state)), self.visible)
        run.announce(state, directory, self.logs.append, self.cfg)
        self.assertEqual(self.keys[-1], "Enter")
        self.assertEqual(self.composer, "")
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(tell.too_long(self.sent[0]))
        self.assertIn("2 review follow-ups", self.sent[0])
        self.assertIn("2 in your plan:", self.sent[0])
        self.assertIn("result.md", self.sent[0])
        self.assertIn(plan.path("fix-api").name, self.sent[0])
        saved = record.read_state(directory)
        self.assertTrue(saved["handed_back"])
        self.assertNotIn("handback_pending", saved)
        result = (directory / "result.md").read_text()
        planned = plan.path("fix-api").read_text()
        for item in state["followups"]:
            self.assertIn(item, result)
            self.assertIn(item, planned)

    def test_any_number_of_followups_is_counted_and_retained(self):
        directory, state = self.followups(1000)
        line = run.handback_line(state, directory, self.cfg)
        self.assertIsNone(tell.too_long(line))
        self.assertIn("1000 review follow-ups", line)
        self.assertIn("1000 in your plan:", line)
        result = (directory / "result.md").read_text()
        for item in state["followups"]:
            self.assertIn(item, result)

    def test_refused_followups_and_fix_runs_stay_whole_in_the_result(self):
        directory, state = self.result(followups=["api.py:1 - " + "evidence " * 200])
        refusal = "the check cannot run: " + "failure evidence " * 100
        handed = {"followup_plan": [{"outcome": "Fix api.py:1", "refused": refusal}],
                  "followup_runs": [f"fix-api-{i}" for i in range(100)]}
        run.followups_handed(directory, state, handed)
        line = run.handback_line(state, directory, self.cfg)
        self.assertIsNone(tell.too_long(line))
        self.assertIn("1 refused by your plan", line)
        self.assertIn("100 fix runs", line)
        result = (directory / "result.md").read_text()
        self.assertIn(refusal, result)
        for name in handed["followup_runs"]:
            self.assertIn("- " + name + "\n", result)

    def test_a_fitting_ending_is_unchanged_including_at_the_bound(self):
        directory, state = self.result(followup_plan=[{"outcome": "Fix api.py:1"}])
        expected = (f"run {directory.name} finished PASS merged: {state['pr']}. "
                    f"Result: {directory / 'result.md'}. "
                    "Review follow-ups now in your plan, yours to build: Fix api.py:1. "
                    "Each is checked by the reviewer's probe until `ak plan check N` puts "
                    "your fix's own test in its place. Decide the next step.")
        self.assertEqual(run.handback_line(state, directory, self.cfg), expected)
        with patch.object(tell, "longest", return_value=len(expected)):
            self.assertEqual(run.handback_line(state, directory, self.cfg), expected)
        with patch.object(tell, "longest", return_value=len(expected) - 1):
            line = run.handback_line(state, directory, self.cfg)
            self.assertIsNone(tell.too_long(line))
            self.assertIn("1 review follow-ups", line)
            self.assertNotEqual(line, expected)

    def test_the_same_byte_bound_as_tell_is_applied(self):
        directory, state = self.result()
        state["pr"] = "é" * 250
        with patch.object(tell, "MAX_BYTES", 600):
            line = run.handback_line(state, directory, self.cfg)
            self.assertIsNone(tell.too_long(line))
            self.assertLessEqual(len(line.encode("utf-8")), tell.MAX_BYTES)
            self.assertNotIn(state["pr"], line)

    def test_the_rounds_final_line_is_bounded_after_its_longer_action(self):
        directory, state = self.result(state="fail", verdict="FAIL",
                                       round_summaries=[{"round": 1, "verdict": "FAIL",
                                                         "done_when": True, "summary": "Fix api.py"}],
                                       error="no reason was recorded")
        # The old ending fits; changing it into a review-round notice pushes it over.
        expected = run.handback_line(state, directory, self.cfg)
        with patch.object(tell, "longest", return_value=len(expected) + 5):
            run.tell_own_pr_round(self.cfg, directory, state, self.logs.append)
            self.assertIsNone(tell.too_long(self.sent[-1]))
        self.assertIn("review round 1/3 FAIL", self.sent[-1])
        self.assertIn("Fix the findings and push to this PR", self.sent[-1])
        self.assertEqual(self.composer, "")
        self.assertEqual(record.read_state(directory)["own_pr_round_told"], 1)

    def test_a_maintainer_decision_uses_the_same_followup_bound(self):
        directory, state = self.followups(2)
        with patch.object(run, "run_for_pr", return_value=(directory, state)):
            self.assertTrue(watch.say(False, self.logs.append, "The maintainer merged the PR",
                                      state["pr"], "fix-api", merged=True))
        self.assertIsNone(tell.too_long(self.sent[-1]))
        self.assertIn("2 review follow-ups", self.sent[-1])
        self.assertEqual(self.composer, "")

    def test_a_revived_seats_fresh_notice_is_bounded_after_the_addition(self):
        directory, state = self.result(title="The full task " * 100)
        with patch.object(orch, "watching", return_value=False), \
                patch.object(orch, "ensure", return_value="fresh"), \
                patch.object(watch, "is_preexisting", return_value=False):
            run.announce(state, directory, self.logs.append, self.cfg)
        self.assertIsNone(tell.too_long(self.sent[-1]))
        self.assertIn("earlier conversation could not be resumed", self.sent[-1])
        self.assertIn("result.md", self.sent[-1])
        self.assertEqual(self.composer, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
