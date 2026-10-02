"""Landing re-review spends no task round; only fixing its findings does.

Offline: local git repos, fake checks and workers, and an isolated HOME.
"""

from contextlib import nullcontext
import copy
import os
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from test_merge_step import make_loop, make_repos
from fixtures.hand_in import submitting
from agentkit import run


class LandingReviewSpendsNoRound(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        _, owner, self.wt = make_repos(self.root)
        self.lp, self.run_dir, _ = make_loop(self.root, self.wt, rounds=3, spent=3)
        self.lp.state["merge_method"] = "merge"
        self.lp.save()
        (owner / "base.txt").write_text("target moved\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "move target")
        run.git(owner, "push", "origin", "main")
        run.git(self.wt, "fetch", "origin")
        self.tip = run.git(self.wt, "rev-parse", "origin/main")
        self.events = []
        self.verdicts = iter(["PASS"])
        self.stack.enter_context(patch.object(run, "run_done_when",
                                              return_value=(True, "$ true\n[exit 0]\n")))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=submitting(self.reviewer)))
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fixer))
        self.stack.enter_context(patch.object(run, "pickup_new_code"))
        self.stack.enter_context(patch.object(run, "merge_turn",
                                              side_effect=lambda *a, **_kw: nullcontext()))

    def reviewer(self, cfg, name, body, workspace, out, role, session, log, limit=None, **_kw):
        self.assertEqual(role, "reviewer")
        self.events.append(("reviewer", out.parent.name))
        verdict = next(self.verdicts)
        finding = "- work.txt:1 - the merged tree breaks\n" if verdict == "FAIL" else "- none\n"
        answer = f"VERDICT: {verdict}\n\n## Findings\n{finding}"
        out.mkdir(parents=True)
        (out / "final.md").write_text(answer)
        return 0, answer, session, False

    def fixer(self, lp, role, text, name, **_kw):
        self.assertEqual(role, "fixer")
        self.assertIn("work.txt:1 - the merged tree breaks", text)
        self.events.append(("fixer", lp.rnd))
        lp.round_dir.mkdir(parents=True, exist_ok=True)
        return "## Summary\nFixed the findings."

    def pending_merge(self, spent=3):
        self.lp.state["round_summaries"] = self.lp.state["round_summaries"][:spent]
        self.lp.rnd = spent
        self.history = copy.deepcopy(self.lp.state["round_summaries"])
        run.pending_review(self.lp, "Re-review after the merge of origin/main.")
        run.git(self.wt, "merge", "--no-edit", self.tip)

    def legacy_merge(self, spent=3):
        self.pending_merge(spent)
        # Before landing reviews stopped spending rounds, this was the saved receipt.
        self.lp.state["review_pending"]["round"] = spent + 1
        self.lp.state["review_pending"].pop("record")
        self.lp.save()
        saved = run.read_state(self.run_dir)
        return run.Loop(self.cfg, self.run_dir, saved, {}, self.lp.log, self.wt,
                        "body", ["true"], "context", [])

    def land(self, lp=None):
        lp = lp or self.lp

        def deliver():
            self.assertTrue(run.current_review(lp))
            self.assertTrue(run.integrated(lp.wt, self.tip))
            lp.state["merged"] = True
            lp.save()
            return True

        return run.land(lp, "origin/main", lambda: run.integrate(lp, "origin/main"), deliver)

    def assert_no_round(self, lp):
        state = run.read_state(self.run_dir)
        self.assertEqual(state["round_summaries"], self.history)
        self.assertEqual(lp.rnd, len(self.history))
        self.assertEqual(state["rounds"], 3)
        self.assertNotIn("review_pending", state)
        self.assertNotIn("round budget", (self.run_dir / "log.txt").read_text())

    def test_pass_at_the_budget_lands_without_spending_a_round(self):
        self.pending_merge()
        self.assertTrue(self.land())
        self.assertEqual(self.events, [("reviewer", "round-3")])
        self.assert_no_round(self.lp)
        self.assertTrue(run.read_state(self.run_dir)["merged"])

    def test_pass_below_the_budget_spends_no_round(self):
        self.pending_merge(spent=1)
        self.assertTrue(self.land())
        self.assertEqual(self.events, [("reviewer", "round-1")])
        self.assert_no_round(self.lp)

    def test_fail_with_findings_spends_only_the_fixer_round(self):
        self.pending_merge(spent=1)
        self.verdicts = iter(["FAIL", "PASS"])
        self.assertTrue(self.land())
        self.assertEqual(self.events, [("reviewer", "round-1"), ("fixer", 2),
                                       ("reviewer", "round-2")])
        state = run.read_state(self.run_dir)
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2])
        self.assertEqual(state["round_summaries"][:1], self.history)
        self.assertTrue(state["merged"])

    def test_fail_at_the_budget_is_reviewed_and_keeps_its_findings(self):
        self.pending_merge()
        self.verdicts = iter(["FAIL"])
        self.assertFalse(self.land())
        self.assertEqual(self.events, [("reviewer", "round-3")])
        self.assert_no_round(self.lp)
        state = run.read_state(self.run_dir)
        self.assertEqual(state["review"]["verdict"], "FAIL")
        self.assertIn("work.txt:1 - the merged tree breaks", state["findings"])
        self.assertFalse(state["merged"])

    def test_interrupted_landing_review_resumes_at_the_budget_and_lands(self):
        self.history = copy.deepcopy(self.lp.state["round_summaries"])
        with patch.object(run, "run_done_when", side_effect=run.Exhausted("check interrupted")):
            with self.assertRaisesRegex(run.Exhausted, "check interrupted"):
                run.integrate(self.lp, "origin/main")
        saved = run.read_state(self.run_dir)
        resumed = run.Loop(self.cfg, self.run_dir, saved, {}, self.lp.log, self.wt,
                           "body", ["true"], "context", [])
        run.rounds(resumed)
        self.assertTrue(self.land(resumed))
        self.assertEqual(self.events, [("reviewer", "round-3")])
        self.assert_no_round(resumed)
        self.assertTrue(run.read_state(self.run_dir)["merged"])

    def test_legacy_landing_review_resumes_at_the_budget_and_lands(self):
        resumed = self.legacy_merge()
        run.rounds(resumed)
        self.assertTrue(self.land(resumed))
        self.assertEqual(self.events, [("reviewer", "round-3")])
        self.assert_no_round(resumed)
        self.assertTrue(run.read_state(self.run_dir)["merged"])

    def test_legacy_landing_review_below_the_budget_spends_only_the_fixer_round(self):
        resumed = self.legacy_merge(spent=1)
        self.verdicts = iter(["FAIL", "PASS"])
        run.rounds(resumed)
        self.assertTrue(self.land(resumed))
        self.assertEqual(self.events, [("reviewer", "round-1"), ("fixer", 2),
                                       ("reviewer", "round-2")])
        state = run.read_state(self.run_dir)
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2])
        self.assertEqual(state["round_summaries"][:1], self.history)
        self.assertTrue(state["merged"])

    def test_legacy_landing_review_fail_at_the_budget_keeps_its_findings(self):
        resumed = self.legacy_merge()
        self.verdicts = iter(["FAIL"])
        run.rounds(resumed)
        self.assertEqual(self.events, [("reviewer", "round-3")])
        self.assert_no_round(resumed)
        state = run.read_state(self.run_dir)
        self.assertEqual(state["review"]["verdict"], "FAIL")
        self.assertIn("work.txt:1 - the merged tree breaks", state["findings"])
        self.assertFalse(state["merged"])

    def test_changed_checkout_resume_does_not_integrate_a_no_merge_run(self):
        self.lp.state["round_summaries"] = self.lp.state["round_summaries"][:1]
        self.lp.rnd = 1
        self.lp.state.update(no_merge=True, merge_method="rebase")
        self.lp.opts["--no-merge"] = True
        self.lp.save()
        (self.wt / "changed.txt").write_text("changed after review\n")
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-m", "change reviewed checkout")
        head = run.git(self.wt, "rev-parse", "HEAD")
        with patch.object(run, "run_done_when", side_effect=run.Exhausted("check interrupted")):
            with self.assertRaisesRegex(run.Exhausted, "check interrupted"):
                run.rounds(self.lp)
        saved = run.read_state(self.run_dir)
        resumed = run.Loop(self.cfg, self.run_dir, saved, self.lp.opts, self.lp.log, self.wt,
                           "body", ["true"], "context", [])
        with patch.object(run, "integrate", wraps=run.integrate) as integrate:
            run.rounds(resumed)
        integrate.assert_not_called()
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), head)
        self.assertFalse(run.integrated(self.wt, self.tip))
        self.assertEqual(saved["round_summaries"][-1]["round"], 2)
        self.assertEqual(self.events, [("reviewer", "round-2")])
        self.assertTrue(run.current_review(resumed))
        self.assertTrue(saved["no_merge"])
        self.assertFalse(saved["merged"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
