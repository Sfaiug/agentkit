"""A failed clean-rebase gate gets landing fixers before a review, without task rounds.

Offline: real local git repos, fake gates and workers, and an isolated HOME.
Both sides edit the same file without a conflict; only their combined tree fails.
"""

from contextlib import ExitStack, nullcontext
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import host, config, gc, run, usage, watch
from test_merge_step import make_loop, make_repos


class LandingRerunSpendsNoRound(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-landing-rerun-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": ""}))
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        _, self.owner, self.wt = make_repos(self.root)
        self.commit(self.owner, "base.txt", "1\n2\n3\n4\n5\n")
        run.git(self.owner, "push", "origin", "main")
        run.git(self.wt, "fetch", "origin")
        run.git(self.wt, "rebase", "origin/main")
        self.commit(self.wt, "base.txt", "branch\n2\n3\n4\n5\n")
        self.lp, self.run_dir, _ = make_loop(config.RUNS, self.wt, rounds=3, spent=3)
        self.lp.state["done_when_failure"] = {"every": []}
        self.lp.save()
        self.history = copy.deepcopy(self.lp.state["round_summaries"])
        self.commit(self.owner, "base.txt", "1\n2\n3\n4\ntarget\n")
        run.git(self.owner, "push", "origin", "main")
        self.tip = run.git(self.owner, "rev-parse", "HEAD")
        self.events = []
        self.verdicts = iter(["PASS"])
        self.fix_after = 1
        self.fixes = 0
        self.stack.enter_context(patch.object(run, "target_fails", return_value=False))
        self.stack.enter_context(patch.object(run, "run_done_when", side_effect=self.gate))
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fixer))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=submitting(self.reviewer)))

    def commit(self, cwd, name, text):
        (cwd / name).write_text(text)
        run.git(cwd, "add", name)
        run.git(cwd, "commit", "-m", f"edit {name}")

    def gate(self, cmds, wt, out, *args, **_kw):
        out.parent.mkdir(parents=True, exist_ok=True)
        text = (Path(wt) / "base.txt").read_text()
        self.assertIn(text, ("branch\n2\n3\n4\ntarget\n", "branch\n2\n3\n4\ngreen\n"))
        ok = text.endswith("green\n") or (Path(wt) / "fixed.txt").exists()
        self.events.append(("gate", ok))
        return ok, ("$ check\n[exit 0]\n" if ok else
                    "$ check\n[exit 1]\nshared file needs fixed.txt\n")

    def fixer(self, lp, role, text, name, **_kw):
        self.assertEqual(role, "fixer")
        self.assertIn("shared file needs fixed.txt", text)
        self.assertEqual(lp.state["review_pending"]["round"], self.history[-1]["round"])
        self.assertIs(lp.state["review_pending"]["record"], False)
        self.events.append(("fixer", lp.rnd))
        self.fixes += 1
        name = "fixed.txt" if self.fixes == self.fix_after else f"attempt{self.fixes}.txt"
        self.commit(lp.wt, name, "fixed\n")
        return "## Summary\nFixed the shared file gate."

    def reviewer(self, cfg, name, body, workspace, out, role, session, log,
                 limit=None, **_kw):
        self.assertEqual(role, "reviewer")
        self.assertEqual(self.events[-1], ("gate", True), "reviewed a failing gate")
        self.events.append(("reviewer", out.parent.name))
        verdict = next(self.verdicts)
        finding = "- base.txt:1 - the fix skips a check\n" if verdict == "FAIL" else "- none\n"
        answer = f"VERDICT: {verdict}\n\n## Findings\n{finding}"
        out.mkdir(parents=True)
        (out / "final.md").write_text(answer)
        return 0, answer, session, False

    def assert_no_task_round(self):
        state = run.read_state(self.run_dir)
        self.assertEqual(state["round_summaries"], self.history)
        self.assertEqual(state["done_when_failure"], {"every": []})
        self.assertEqual(self.lp.rnd, 3)
        self.assertNotIn("round budget", (self.run_dir / "log.txt").read_text())

    def test_failed_rerun_fixes_before_review_at_the_spent_budget(self):
        self.assertTrue(run.integrate(self.lp, "origin/main"))
        self.assertEqual(self.events, [("gate", False), ("fixer", 3), ("gate", True),
                                       ("reviewer", "round-3")])
        self.assert_no_task_round()
        self.assertTrue(run.current_review(self.lp))
        self.assertEqual(self.lp.lap_every_sha, run.git(self.wt, "rev-parse", "HEAD"))

    def test_third_landing_fixer_can_pass_without_reviewing_failed_gates(self):
        self.fix_after = 3
        self.assertTrue(run.integrate(self.lp, "origin/main"))
        self.assertEqual(self.events, [("gate", False)] +
                         [("fixer", 3), ("gate", False)] * 2 +
                         [("fixer", 3), ("gate", True), ("reviewer", "round-3")])
        self.assert_no_task_round()
        self.assertTrue(run.current_review(self.lp))

    def test_three_failed_landing_fixers_park_without_a_reviewer(self):
        self.fix_after = 4
        self.assertFalse(run.integrate(self.lp, "origin/main"))
        self.assertEqual(self.events, [("gate", False)] + [("fixer", 3), ("gate", False)] * 3)
        self.assert_no_task_round()
        state = run.read_state(self.run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertFalse(state["merge_failed"])
        self.assertEqual(state["waiting_on"], {"ref": "origin/main", "sha": self.tip})
        self.assertIn("3 fixer rounds", state["merge_note"])
        self.assertIn("shared file needs fixed.txt", state["merge_note"])

    def assert_parked_resume(self, spent, repaired=True, abort=None, unreachable=False):
        self.history = self.history[:spent]
        self.lp.state["round_summaries"] = copy.deepcopy(self.history)
        self.lp.rnd = spent
        self.lp.save()
        self.fix_after = run.CONFLICT_ROUNDS + 1
        self.assertFalse(run.integrate(self.lp, "origin/main"))
        self.assertEqual(self.fixes, run.CONFLICT_ROUNDS)
        self.assertFalse(run.current_review(self.lp))
        before = len(self.events)
        if abort:
            self.commit(self.owner, "base.txt", "conflict\n2\n3\n4\ntarget\n")
        elif repaired:
            self.commit(self.owner, "base.txt", "1\n2\n3\n4\ngreen\n")
        else:
            self.commit(self.owner, "other.txt", "target moved\n")
        run.git(self.owner, "push", "origin", "main")
        tip = run.git(self.owner, "rev-parse", "HEAD")
        (self.run_dir / "task.md").write_text(
            f"---\nrepo: {self.wt}\nbase: origin/main\nrounds: 3\n---\n"
            "# Landing rerun\n\n## Done when\n```bash\ntrue\n```\n")
        binaries = self.root / "bin"
        binaries.mkdir()
        tmux = binaries / "tmux"
        tmux.write_text("#!/bin/sh\nexit 1\n")
        tmux.chmod(0o755)

        def deliver(lp, **_kw):
            self.assertTrue(run.current_review(lp))
            self.assertTrue(run.integrated(lp.wt, tip))
            lp.state.update(merged=True, merge_failed=False, merge_note=None)

        with patch.dict(os.environ, {"PATH": f"{binaries}:{os.environ['PATH']}",
                                     "AGENTKIT_DISCORD_WEBHOOK": "off"}), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(usage, "pick_order", return_value=["opus", "astra"]), \
                patch.object(gc, "disk_pressure", return_value=False), \
                patch.object(run.notify, "shaped", side_effect=AssertionError("notification")), \
                patch.object(run, "launcher_world", return_value=nullcontext(True)), \
                patch.object(run, "hand_back", return_value=True), \
                patch.object(run, "stop_run_tree"), \
                patch.object(run.history, "Sampler"), \
                patch.object(run.history, "sample_rss", return_value=None), \
                patch.object(run, "merge", side_effect=deliver):
            if abort:
                head = run.git(self.wt, "rev-parse", "HEAD")
                how = run.how_to_integrate(self.lp)

                def unfinished(lp, role, text, name, **_kw):
                    self.assertEqual((role, name), ("fixer", f"{how}-fixer"))
                    self.assertTrue(run.in_progress(lp.wt, how))
                    self.events.append(("conflict-fixer", lp.rnd))
                    if abort == "exhausted":
                        raise run.Exhausted("conflict fixer interrupted")
                    return "## Summary\nCould not finish the conflict."

                with patch.object(run, "execute", side_effect=unfinished):
                    self.assertEqual(run.cmd_resume([self.run_dir.name]), 1)
                state = run.read_state(self.run_dir)
                self.assertEqual(state["state"], "exhausted" if abort == "exhausted" else "waiting")
                attempts = 1 if abort == "exhausted" else run.CONFLICT_ROUNDS
                self.assertEqual(self.events[before:], [("conflict-fixer", spent)] * attempts)
                self.assertEqual(state["round_summaries"], self.history)
                self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), head)
                self.assertFalse(run.in_progress(self.wt, how))
                self.commit(self.owner, "base.txt", "1\n2\n3\n4\ngreen\n")
                run.git(self.owner, "push", "origin", "main")
                tip = run.git(self.owner, "rev-parse", "HEAD")
                before = len(self.events)
            if unreachable:
                config.session_path("acme").write_text("{}")
                parked = run.read_state(self.run_dir)
                parked["launched_session"] = "acme"
                pending = copy.deepcopy(parked["review_pending"])
                for fault in ("fetch", "upstream"):
                    with self.subTest(fault=fault):
                        run.save_state(self.run_dir, copy.deepcopy(parked))
                        if fault == "upstream":
                            run.git(self.wt, "update-ref", "-d", "refs/remotes/origin/main")
                        reason = ("git fetch origin failed" if fault == "fetch" else
                                  "origin/main does not exist on origin")
                        result = (1, "origin unavailable") if fault == "fetch" else (0, "")
                        with patch.object(run, "fetch", return_value=result):
                            try:
                                run.cmd_resume([self.run_dir.name])
                            except config.Error as exc:
                                self.assertIn(reason, str(exc))
                        state = run.read_state(self.run_dir)
                        self.assertEqual(state["state"], "error")
                        self.assertIn(reason, state["error"])
                        self.assertEqual(state["review_pending"], pending)
                        self.assertEqual(state["round_summaries"], self.history)
                        self.assertEqual(len(self.events), before)
                        self.assertTrue(run.going(state))
                        with patch.object(run, "spawn_bg", return_value=0) as launch:
                            watch.resume_errored(log=self.lp.log, now=state["error_retry_at"])
                        launch.assert_called_once_with(
                            self.run_dir, ["resume", self.run_dir.name],
                            expected=run.read_state(self.run_dir), park_as=True)
            self.assertEqual(run.cmd_resume([self.run_dir.name]), 0)
        state = run.read_state(self.run_dir)
        fixes = [] if repaired else [("gate", False), ("fixer", spent)]
        self.assertEqual(self.events[before:], fixes +
                         [("gate", True), ("reviewer", f"round-{spent}")])
        self.assertEqual(state["round_summaries"], self.history)
        self.assertEqual(state["rounds"], 3)
        self.assertEqual(state["done_when_failure"], {"every": []})
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertEqual(state["review"]["head_sha"], run.git(self.wt, "rev-parse", "HEAD"))
        self.assertNotIn("round budget", (self.run_dir / "log.txt").read_text())

    def test_parked_retry_rebases_before_review_at_the_spent_budget(self):
        self.assert_parked_resume(spent=3)

    def test_parked_retry_rebases_before_review_with_rounds_left(self):
        self.assert_parked_resume(spent=1)

    def test_parked_retry_still_failing_gets_a_landing_fixer(self):
        self.assert_parked_resume(spent=3, repaired=False)

    def test_parked_retry_survives_an_unfinished_rebase_conflict(self):
        self.assert_parked_resume(spent=3, abort="unfinished")

    def test_parked_retry_survives_an_unfinished_merge_conflict(self):
        self.lp.state["merge_method"] = "merge"
        self.assert_parked_resume(spent=3, abort="unfinished")

    def test_parked_retry_survives_an_interrupted_conflict_fixer(self):
        self.assert_parked_resume(spent=3, abort="exhausted")

    def test_unreachable_target_keeps_a_landing_retry_scheduled(self):
        self.assert_parked_resume(spent=3, unreachable=True)

    def test_interrupted_landing_review_resumes_at_the_same_round(self):
        with patch.object(run, "call_retrying", side_effect=run.Exhausted("review interrupted")):
            with self.assertRaisesRegex(run.Exhausted, "review interrupted"):
                run.integrate(self.lp, "origin/main")
        state = run.read_state(self.run_dir)
        self.assertEqual(state["review_pending"]["round"], 3)
        self.assertIs(state["review_pending"]["record"], False)
        resumed = run.Loop(self.lp.cfg, self.run_dir, state, {}, self.lp.log, self.wt,
                           "body", ["true"], "context", [])
        with patch.object(run, "execute", side_effect=AssertionError("unexpected fixer")):
            run.rounds(resumed)
        self.assertEqual(resumed.state["round_summaries"], self.history)
        self.assertTrue(run.current_review(resumed))

    def test_a_real_review_failure_spends_only_the_next_task_fix_round(self):
        self.history = self.history[:1]
        self.lp.state["round_summaries"] = copy.deepcopy(self.history)
        self.lp.rnd = 1
        self.lp.save()
        self.verdicts = iter(["FAIL", "PASS"])

        def fixer(lp, role, text, name, **_kw):
            if name == "rerun-fixer":
                return self.fixer(lp, role, text, name)
            self.assertEqual(name, "executor")
            self.assertIn("base.txt:1 - the fix skips a check", text)
            self.events.append(("task-fixer", lp.rnd))
            return "## Summary\nFixed the review findings."

        with patch.object(run, "execute", side_effect=fixer):
            self.assertTrue(run.integrate(self.lp, "origin/main"))
        self.assertEqual(self.events, [("gate", False), ("fixer", 1), ("gate", True),
                                       ("reviewer", "round-1"), ("task-fixer", 2),
                                       ("gate", True), ("reviewer", "round-2")])
        self.assertEqual([entry["round"] for entry in self.lp.state["round_summaries"]], [1, 2])
        self.assertTrue(run.current_review(self.lp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
