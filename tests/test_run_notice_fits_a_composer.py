"""Run notices share the typed line's bound; the full result keeps every follow-up.

Offline: a temporary HOME and a fake seat whose composer shows only a prefix of an
oversized line. The real confirmed send must get its Enter and leave no unsent notice.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import Sandbox
from agentkit import config, orch, record, run, watch, worktrees


PR = "https://github.com/acme/widget/pull/7"


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
        self.visible = watch.longest(self.cfg)
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
            "no_merge": True,
            "rounds": 3, "round_summaries": [], "findings": "", "branch": "ak/fix-api",
            "base_sha": "a" * 40, "worktree": str(self.root), **extra})
        state = record.read_state(directory)
        with patch.object(run, "git", return_value="(fixture diff)"):
            run.write_result(directory, state, [])
        return directory, state

    def followups(self, count, **extra):
        """A pass not merged whose reason outgrows any composer, with that many review
        follow-ups: only its result holds them whole."""
        items = [f"api.py:{i + 1} - defect {i + 1}: " + "complete evidence " * 25
                 for i in range(count)]
        return self.result(followups=items, merge_note="the delivery stopped: "
                           + "the whole reason " * 100, **extra)

    def test_a_long_ending_gets_enter_and_leaves_nothing_pending(self):
        directory, state = self.followups(2)
        # The original notice is larger than the whole composer, even without its result.
        self.assertGreater(len(state["merge_note"]), self.visible)
        run.announce(state, directory, self.logs.append, self.cfg)
        self.assertEqual(self.keys[-1], "Enter")
        self.assertEqual(self.composer, "")
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(watch.too_long(self.sent[0]))
        self.assertIn("2 review follow-ups", self.sent[0])
        self.assertIn("result.md", self.sent[0])
        saved = record.read_state(directory)
        self.assertTrue(saved["handed_back"])
        self.assertNotIn("handback_pending", saved)
        result = (directory / "result.md").read_text()
        self.assertIn(state["merge_note"], result)
        for item in state["followups"]:
            self.assertIn(item, result)

    def test_any_number_of_followups_is_counted_and_retained(self):
        directory, state = self.followups(1000)
        line = run.handback_line(state, directory, self.cfg)
        self.assertIsNone(watch.too_long(line))
        self.assertIn("1000 review follow-ups", line)
        result = (directory / "result.md").read_text()
        for item in state["followups"]:
            self.assertIn(item, result)

    def test_a_merges_plan_lines_refusals_and_fix_runs_are_whole_in_its_result(self):
        """A merge is typed into no seat: its result is what names what it handed on."""
        directory, state = self.result(merged=True, pr=PR,
                                       followups=["api.py:1 - " + "evidence " * 200])
        refusal = "the check cannot run: " + "failure evidence " * 100
        handed = {"followup_plan": [{"outcome": "Fix api.py:1", "refused": refusal}],
                  "followup_runs": [f"fix-api-{i}" for i in range(100)]}
        run.followups_handed(directory, state, handed)
        result = (directory / "result.md").read_text()
        self.assertIn(refusal, result)
        for name in handed["followup_runs"]:
            self.assertIn("- " + name + "\n", result)

    def test_a_fitting_ending_is_unchanged_including_at_the_bound(self):
        directory, state = self.result(followups=["api.py:1 - a defect"])
        expected = (f"run {directory.name} finished PASS not merged: --no-merge. "
                    f"Result: {directory / 'result.md'}. Decide the next step.")
        self.assertEqual(run.handback_line(state, directory, self.cfg), expected)
        with patch.object(watch, "longest", return_value=len(expected)):
            self.assertEqual(run.handback_line(state, directory, self.cfg), expected)
        with patch.object(watch, "longest", return_value=len(expected) - 1):
            line = run.handback_line(state, directory, self.cfg)
            self.assertIsNone(watch.too_long(line))
            self.assertIn("1 review follow-ups", line)
            self.assertNotEqual(line, expected)

    def test_the_same_byte_bound_as_tell_is_applied(self):
        directory, state = self.result()
        state["merge_note"] = "é" * 250
        with patch.object(watch, "MAX_BYTES", 600):
            line = run.handback_line(state, directory, self.cfg)
            self.assertIsNone(watch.too_long(line))
            self.assertLessEqual(len(line.encode("utf-8")), watch.MAX_BYTES)
            self.assertNotIn(state["merge_note"], line)

    def test_a_maintainer_decision_uses_the_same_followup_bound(self):
        directory, state = self.followups(2, pr=PR)
        with patch.object(run, "run_for_pr", return_value=(directory, state)):
            self.assertTrue(watch.say(False, self.logs.append, "The maintainer requested changes "
                                      + "on every line " * 100, state["pr"], "fix-api"))
        self.assertIsNone(watch.too_long(self.sent[-1]))
        self.assertIn("2 review follow-ups", self.sent[-1])
        self.assertEqual(self.composer, "")

    def test_a_revived_seats_fresh_notice_is_bounded_after_the_addition(self):
        directory, state = self.result(title="The full task " * 100)
        with patch.object(orch, "watching", return_value=False), \
                patch.object(orch, "ensure", return_value="fresh"), \
                patch.object(watch, "is_preexisting", return_value=False):
            run.announce(state, directory, self.logs.append, self.cfg)
        self.assertIsNone(watch.too_long(self.sent[-1]))
        self.assertIn("earlier conversation could not be resumed", self.sent[-1])
        self.assertIn("result.md", self.sent[-1])
        self.assertEqual(self.composer, "")

    def test_a_saved_ending_keeps_its_followups_before_typing(self):
        reason = "the delivery stopped: " + "failure evidence " * 100 + "whole reason"
        items = ["api.py:1 - a defect\ncomplete reviewer evidence"]
        directory, state = self.result(followups=items, handback_pending=True, merge_note=reason)
        result = directory / "result.md"
        result.write_text("# PASS\n\nFixed API.\n")  # a report saved before follow-ups were rendered
        line = run.handback_line(state, directory, self.cfg)
        saved = result.read_text()
        self.assertIsNone(watch.too_long(line))
        self.assertIn(reason, saved)
        self.assertIn("complete reviewer evidence", saved)
        self.assertIn("Fixed API.", saved)
        self.assertEqual(run.handback_line(state, directory, self.cfg), line)
        self.assertEqual(result.read_text(), saved)  # a retry retains the evidence without copying it

    def test_a_compact_recovery_retains_its_cause_and_rerun_warning(self):
        reason = "a process stopped during a remote write " * 30 + "interruption cause"
        directory = self.ended("fix-api", owner="fix-api", state="interrupted", verdict=None,
                               interruption_reason=reason, interrupted_at=10000, started_at=9990)
        with patch.object(orch, "watching", return_value=False), \
                patch.object(orch, "ensure", return_value=False), \
                patch.object(watch, "orphan_fresh", return_value=True), \
                patch.object(watch, "is_preexisting", return_value=False):
            run.notify_recovery(directory, record.read_state(directory))
        self.assertIsNone(watch.too_long(self.sent[-1]))
        self.assertIn("result.md", self.sent[-1])
        saved = (directory / "result.md").read_text()
        self.assertIn(reason, saved)
        self.assertIn("Do not automatically rerun it; check for effects from the interrupted attempt.",
                      saved)
        self.assertEqual(record.read_state(directory)["recovery_notified"], "orchestrator")

    def test_an_after_merge_failure_survives_delivery_and_episode_cleanup(self):
        now = 2000000
        evidence = "deployment missing " * 100 + "deployment evidence"
        directory, state = self.result(
            merged=True, pr=PR, repo=str(self.root), finished_at=now - watch.AFTER_MERGE_WINDOW - 1,
            merge_sha="a" * 40, target="origin/main",
            health={"command": "probe", "output": evidence})
        episodes = {}
        with patch.object(watch, "after_merge_sha", return_value="a" * 40), \
                patch.object(watch, "after_merge_status", return_value=("passed", None, None)):
            watch.after_merge_checks(episodes, False, self.logs.append, now=now)
            self.assertEqual(len(self.sent), 1)
            self.assertIsNone(watch.too_long(self.sent[0]))
            self.assertIn("result.md", self.sent[0])
            self.assertNotIn("health", record.read_state(directory))
            episode = episodes["after_merge"][watch.after_merge_repo(state["pr"])[3]]
            self.assertIn("notified", episode)
            self.assertNotIn("pending", episode)
            self.assertIn(evidence, (directory / "result.md").read_text())
            watch.after_merge_checks(episodes, False, self.logs.append, now=now + 1)
        self.assertEqual(episodes["after_merge"], {})
        self.assertIn(evidence, (directory / "result.md").read_text())

    def test_a_report_finishing_after_failure_delivery_keeps_the_whole_notice(self):
        directory, state = self.result(merged=True, pr=PR, repo=str(self.root), finished_at=9999,
                                       merge_sha="a" * 40, target="origin/main")
        details = "https://ci.acme.example/build?diagnostic=" + "deployment-error-" * 80
        episodes = {}

        def during_diff(*_args, **_kw):
            # The loop publishes its merged record before waiting on the report's diff.
            watch.after_merge_checks(episodes, False, self.logs.append, now=10000)
            return "(fixture diff)"

        with patch.object(run, "git", side_effect=during_diff), \
                patch.object(watch, "after_merge_sha", return_value="a" * 40), \
                patch.object(watch, "after_merge_health", return_value=None), \
                patch.object(watch, "gh_json", return_value=([{"check_runs": [{
                    "name": "release-gate", "status": "completed", "conclusion": "failure",
                    "details_url": details}]}], "")):
            run.write_result(directory, state, [], cfg=self.cfg)
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(watch.too_long(self.sent[0]))
        self.assertNotIn(details, self.sent[0])
        episode = episodes["after_merge"][watch.after_merge_repo(state["pr"])[3]]
        self.assertIn("notified", episode)
        self.assertNotIn("pending", episode)
        self.assertIn(details, (directory / "result.md").read_text())

    def test_all_report_rebuilds_keep_saved_notice_details(self):
        directory, state = self.followups(2)
        with patch.object(watch, "longest", return_value=1000000):
            full = run.handback_line(state, directory, self.cfg)
        self.assertTrue(run.hand_back(state, directory, self.logs.append, self.cfg))
        result = directory / "result.md"
        saved = result.read_text()
        (directory / "task.md").write_text("# Fix API\n\n## Done when\n```bash\ntrue\n```\n")
        # A later report no longer has these fields to reconstruct the delivered notice.
        latest = {**state, "followups": [], "merge_note": None}
        rebuilds = (
            ("full result", lambda: run.write_result(directory, latest, [], cfg=self.cfg)),
            ("stopped full result", lambda: run.record_result(directory, latest, cfg=self.cfg)),
            ("stopped short result", lambda: run.record_result(
                directory, {**latest, "worktree": None}, cfg=self.cfg)),
            ("maintainer result", lambda: run.record_decision(
                directory, latest, "The maintainer kept the merged change")))
        with patch.object(run, "git", return_value="(fixture diff)"):
            for name, rebuild in rebuilds:
                with self.subTest(writer=name):
                    result.write_text(saved)
                    rebuild()
                    self.assertIn(full, result.read_text())
                    for item in state["followups"]:
                        self.assertIn(item, result.read_text())
        gone = {**latest, "worktree": None}
        note = "The maintainer confirmed the live fix"
        run.record_decision(directory, gone, note)
        run.record_result(directory, gone, cfg=self.cfg)
        self.assertIn(note, result.read_text())
        self.assertIn(full, result.read_text())

    def test_a_superseded_handback_leaves_the_current_report_untouched(self):
        directory, previous = self.result(
            state="fail", verdict="FAIL", merged=False, pid=10001, finished_at=1000,
            rounds=1, round_summaries=[{"round": 1, "verdict": "FAIL", "done_when": True,
                                        "summary": "Final check failed."}],
            final_check={"outcome": "failed", "where": "landing",
                         "line": "previous attempt's check " + "failure evidence " * 100})
        self.assertTrue(run.failed_at_budget(previous))
        current = {**previous, "pid": 10002, "state": "running", "verdict": None,
                   "finished_at": None, "round_summaries": []}
        record.save_state(directory, current)
        result = directory / "result.md"
        original = "# Current attempt\n\nThe resumed attempt has not finished.\n"
        result.write_text(original)
        self.assertFalse(run.hand_back(previous, directory, self.logs.append, self.cfg))
        self.assertEqual(result.read_text(), original)
        self.assertEqual((self.keys, self.sent), ([], []))

    def test_a_notice_is_not_typed_when_its_omitted_details_cannot_be_saved(self):
        directory, state = self.followups(2)
        result = directory / "result.md"
        result.unlink()
        result.mkdir()
        with self.assertRaises(OSError):
            run.announce(state, directory, self.logs.append, self.cfg)
        self.assertEqual((self.keys, self.sent), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
