"""A failed clean-rebase gate gets landing fixers before a review, without task rounds.

Offline: real local git repos, fake gates and workers, and an isolated HOME.
Both sides edit the same file without a conflict; only their combined tree fails.
"""

from contextlib import ExitStack
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage
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
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
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
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=self.reviewer))

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

    def assert_parked_resume(self, spent):
        self.history = self.history[:spent]
        self.lp.state["round_summaries"] = copy.deepcopy(self.history)
        self.lp.rnd = spent
        self.lp.save()
        self.fix_after = run.CONFLICT_ROUNDS + 1
        self.assertFalse(run.integrate(self.lp, "origin/main"))
        self.assertEqual(self.fixes, run.CONFLICT_ROUNDS)
        self.assertFalse(run.current_review(self.lp))
        before = len(self.events)
        self.commit(self.owner, "base.txt", "1\n2\n3\n4\ngreen\n")
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

        def deliver(lp):
            self.assertTrue(run.current_review(lp))
            self.assertTrue(run.integrated(lp.wt, tip))
            lp.state["merged"] = True

        with patch.dict(os.environ, {"PATH": f"{binaries}:{os.environ['PATH']}",
                                     "AGENTKIT_DISCORD_WEBHOOK": "off"}), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(usage, "pick_order", return_value=["opus", "astra"]), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run.notify, "shaped", side_effect=AssertionError("notification")), \
                patch.object(run, "merge", side_effect=deliver):
            self.assertEqual(run.cmd_resume([self.run_dir.name]), 0)
        state = run.read_state(self.run_dir)
        self.assertEqual(self.events[before:], [("gate", True), ("reviewer", f"round-{spent}")])
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
