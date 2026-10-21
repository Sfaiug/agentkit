"""A harness that loads a branch's own instruction files never reviews it.

A reviewer judges a branch by the base's rules, which ak puts in its prompt.  A harness that
loads the checkout's own instruction files with no switch to stop it (`[instructions]
workspace` in its manifest) would read what the branch wrote instead, so no pick takes one of
its models to review -- a task's and an own pull request's alike -- a `--review` naming one is
refused, and so is a selection whose every reviewer is one.  It still executes: the branch's
instructions are its own.

Offline: invented models on two invented providers, two invented harnesses in a temporary
adapter directory, fake budgets and a temporary HOME; the shipped manifests are only read.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, staffing, turns


class ReviewerReadsNoBranchRules(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-branch-rules-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        adapters = root / "adapters"
        adapters.mkdir()
        (adapters / "readsrules.toml").write_text(
            'version = 1\n[instructions]\nworkspace = ["AGENTS.md", ".rules"]\n')
        (adapters / "plain.toml").write_text("version = 1\n")
        (root / "home").mkdir()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "active_session", return_value=None))
        stack.enter_context(patch.object(config, "HOME", root / "home"))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_ADAPTER_DIR": str(adapters), "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        # the rule-reading model has the most budget left, so only the bar keeps it from reviewing
        self.cfg = {"defaults": {"orchestrator": "acme-reads", "workers": ["acme-reads", "beta-plain"]},
                    "models": {"acme-reads": {"harness": "readsrules", "model": "reads", "effort": "high",
                                              "provider": "acme"},
                               "beta-plain": {"harness": "plain", "model": "plain", "effort": "high",
                                              "provider": "beta"}},
                    "providers": {"acme": {}, "beta": {}}}
        self.providers = {name: {"meters": [{"name": "weekly", "used": used, "pace": used - 50,
                                             "elapsed": 50, "window_secs": 604800,
                                             "resets_at": time.time() + 302400}], "resets": 0}
                          for name, used in (("acme", 5), ("beta", 60))}

    def pick(self, executor=None, reviewer=None, workers=None, reviewers=None):
        return staffing.pick_models(self.cfg, self.providers, executor, reviewer, lambda _: None,
                                    workers=workers, reviewers=reviewers)

    def test_the_shipped_manifests_name_grok_builds_and_antigravitys_files(self):
        with patch.dict(os.environ, {"AGENTKIT_ADAPTER_DIR": ""}):
            found = {name: config.workspace_rules(name) for name, _ in config.manifests()
                     if config.workspace_rules(name)}
        self.assertEqual(found, {"grokbuild": ["AGENTS.md", "CLAUDE.md"],
                                 "antigravity": ["AGENTS.md", "GEMINI.md", ".agents/rules",
                                                 ".agent/rules"]})

    def test_no_reviewer_pick_takes_a_model_that_reads_the_branchs_rules(self):
        both = ["acme-reads", "beta-plain"]
        self.assertEqual(staffing.ready_order(self.cfg, self.providers, both, role="reviewer"),
                         ["beta-plain"])
        self.assertEqual(self.pick(workers=both, reviewers=both), ("acme-reads", "beta-plain"))
        self.assertEqual(self.pick(), ("acme-reads", "beta-plain"))
        self.assertEqual([name for name, _ in staffing.reviewable_models(
            self.cfg, self.providers, both, time.time())], ["beta-plain"])

    def test_it_still_executes(self):
        self.assertEqual(staffing.ready_order(self.cfg, self.providers, ["acme-reads"]),
                         ["acme-reads"])
        self.assertEqual(self.pick(workers=["acme-reads"], reviewers=["beta-plain"]),
                         ("acme-reads", "beta-plain"))

    def test_a_review_naming_one_is_refused_in_one_sentence(self):
        with self.assertRaises(config.Error) as caught:
            self.pick(reviewer="acme-reads")
        self.assertEqual(str(caught.exception),
                         "acme-reads cannot review: its harness loads the branch's own AGENTS.md, .rules")
        # an own pull request's review names its reviewer through the same refusal
        with patch.object(run, "collect_usage", return_value=self.providers), \
                self.assertRaises(config.Error):
            run.preset_review_model(self.cfg, {"--review": "acme-reads", "--review-pr": None})

    def test_a_selection_whose_only_reviewers_read_the_branchs_rules_is_refused(self):
        refusal = staffing.pair_refusal(self.cfg, self.providers, ["beta-plain"],
                                        reviewers=["acme-reads"])
        self.assertEqual(refusal, "none of the reviewers acme-reads may review: acme-reads: its "
                         "harness loads the branch's own AGENTS.md, .rules; mark a reviewer on "
                         "another harness")
        # the one worker left can no longer review its own work either
        self.assertIsNotNone(staffing.pair_refusal(self.cfg, self.providers, ["acme-reads"]))
        with self.assertRaises(turns.QuotaDry):
            self.pick(workers=["beta-plain"], reviewers=["acme-reads"])
        self.assertIsNone(staffing.pair_refusal(self.cfg, self.providers, ["acme-reads"],
                                                reviewers=["acme-reads", "beta-plain"]))

    def test_an_own_pull_request_whose_only_reviewers_read_the_branchs_rules_is_refused(self):
        receipt = {"workers": ["acme-reads"], "reviewers": ["acme-reads"]}
        checkout = Path(os.environ["HOME"]) / "checkout"
        checkout.mkdir()
        values = {"launch_session": None, "collect_usage": self.providers, "saved_findings": "",
                  "pr_view": {"state": "OPEN", "author": "owner", "title": "Mend fence",
                              "baseRefName": "main", "headRefOid": "a" * 40},
                  "pr_writer": (True, "acme-reads", "high"), "own_pr_budget": (3, None),
                  "checkout_for": checkout, "git": "a" * 40, "plan_context": "",
                  "make_worktree": (checkout, "ak/pr-7"), "text_only_pr": False,
                  "own_pr_first_review": None}
        with ExitStack() as stack:
            for name, value in values.items():
                stack.enter_context(patch.object(run, name, return_value=value))
            for name in ("fetch_pr", "join_session_project", "history_start", "exclude_junk",
                         "Loop"):
                stack.enter_context(patch.object(run, name))
            stack.enter_context(patch.object(run, "stamp_origin", side_effect=lambda state: state))
            stack.enter_context(patch.object(run.gc, "before_run"))
            stack.enter_context(patch.object(run.gitcall, "declared_suite", return_value=None))
            stack.enter_context(patch.object(config, "repo_env", return_value={}))
            stack.enter_context(patch.object(run.run_record, "process_owner", return_value={}))
            stack.enter_context(patch.object(run.run_record, "read_state",
                                             side_effect=lambda _: dict(receipt)))
            stack.enter_context(patch.object(run.run_record, "save_state",
                                             side_effect=lambda _, state: receipt.update(state)))
            with self.assertRaises(config.Error) as caught:
                run.review_pr_round(self.cfg, checkout, "https://github.com/acme/widget/pull/7",
                                    {"--review": None}, lambda _: None)
        self.assertEqual(str(caught.exception), staffing.barred_refusal(self.cfg, ["acme-reads"]))


if __name__ == "__main__":
    unittest.main()
