"""Every round's follow-ups survive as the run's, whatever its verdict; flaky check evidence only a passing round's.

Temporary HOME, stubbed reviewers and GitHub; shell checks run only in the fixture.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from fixtures.hand_in import records, submitting
from agentkit import gate, config, hand_in, run, worker
from agentkit import record as run_record

DEFECT = "a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError"
OTHER = "b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"


class FollowupRule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-followup-rule-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": ""}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(run, "history_role_tokens"))
        self.stack.enter_context(patch.object(run.history, "update_run"))
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        # These checks cover carrying weighed records; replay is covered by followup_runs.
        self.stack.enter_context(patch.object(run, "weigh_review", side_effect=
                                             lambda _lp, submitted, *_args, **_kw: submitted))
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        directory = config.RUNS / "followup-fixture"
        directory.mkdir(parents=True)
        state = {"run_id": directory.name, "title": "Follow-up fixture", "state": "running",
                 "base": "origin/main", "base_sha": "abc123", "branch": "ak/fix-api",
                 "rounds": 3, "round_summaries": [], "executor": "executor",
                 "reviewer": "reviewer", "scratch": True, "repo": str(self.workspace),
                 "worktree": str(self.workspace)}
        cfg = {"models": {name: {"harness": "test", "model": name, "effort": "high",
                                "provider": provider}
                          for name, provider in (("executor", "acme"), ("reviewer", "beta"))},
               "providers": {"acme": {}, "beta": {}}}
        self.lp = run.Loop(cfg, directory, state, {}, lambda _: None, self.workspace,
                           "# Fixture", ["true"], "", [])
        self.lp.rnd = 1
        self.lp.save()

    def review(self, *items, verdict="PASS", ok=True, output="$ true\n[exit 0]", record=True,
               code=0):
        answer = f"VERDICT: {verdict}\n\n## Findings\n\n"
        if items:
            answer += "## Follow-ups\n" + "\n".join(
                "- " + item.replace("\n", "\n  ") for item in items) + "\n"
        with patch.object(run, "call_retrying", side_effect=submitting((code, answer, None, False))):
            return run.review(self.lp, "## Summary\nFixture", ok, output, record=record)

    def gate(self):
        command = "if test -f seen; then echo passed; else touch seen; echo broken; exit 1; fi"
        ok, output = gate.run_done_when([command], self.workspace,
                                      self.lp.run_dir / "donewhen.log", set(),
                                      limit=30, run_dir=self.lp.run_dir)
        self.assertTrue(ok, output)
        flake = next(record for record in output.split("\n\n") if record.startswith("flaky: "))
        saved = Path(flake.splitlines()[1].removeprefix("failed output: "))
        self.assertEqual(saved.parent, self.lp.run_dir)
        self.assertEqual(saved.read_text(), "broken\n")
        self.assertEqual(flake.splitlines()[2:], ["broken"])
        return output, flake

    def assert_followups(self, items):
        items = [item if item.startswith("flaky: ") else hand_in.Review(records(
            "VERDICT: PASS\n## Follow-ups\n- " + item.replace("\n", "\n  "))).followups[0]
                 for item in items]
        self.assertEqual(self.lp.state["followups"], items)
        self.assertEqual(run_record.read_state(self.lp.run_dir)["followups"], items)

    def test_every_reviewer_uses_the_same_proven_preexisting_defect_rule(self):
        for role, preamble in worker.PREAMBLES.items():
            if not role.startswith("reviewer"):
                continue
            with self.subTest(role=role):
                self.assertIn(worker.GATE, preamble)
                for words in ("of a kind that would fail a round, with that same evidence",
                              "existed before this task",
                              "prove that with `--before 'base or ancestor commit, or verbatim lines from the named file at base'`",
                              "Hand them in with `ak hand-in follow-up",
                              "Omit everything else everywhere",
                              "however long the follow-ups list is"):
                    self.assertIn(words, preamble)

    def test_a_failed_reviews_follow_ups_are_carried_into_the_pass_its_flakes_not(self):
        output, _ = self.gate()
        self.assertEqual(self.review(DEFECT, verdict="FAIL", output=output), "FAIL")
        self.assert_followups([DEFECT])
        self.lp.rnd += 1
        self.assertEqual(self.review(OTHER), "PASS")
        self.assert_followups([DEFECT, OTHER])

    def test_a_re_review_adds_to_the_list_and_an_empty_one_drops_nothing(self):
        self.review(DEFECT, OTHER)
        self.assert_followups([DEFECT, OTHER])
        updated = DEFECT + "; also reproduced on main before the task"
        self.review(updated, record=False)
        self.assert_followups([DEFECT, OTHER, updated])
        self.review(record=False)
        self.assert_followups([DEFECT, OTHER, updated])
        self.assertIn("## Follow-ups", run.pr_body(self.lp.state))

    def test_a_follow_up_handed_in_again_on_a_new_head_is_kept_once(self):
        def weighed(head):
            row = {"kind": "follow-up", "path": "a.py", "line": 1, "what": "empty input crashes",
                   "why": "callers crash", "evidence": {"run": "false", "commit": head,
                                                       "returncode": 1, "output": ""}}
            return lambda *_args, **_kw: hand_in.Review([row, {"kind": "done"}])
        for head in ("1" * 40, "2" * 40):   # the fixer's commit between rounds moves the head
            with patch.object(run, "weigh_review", side_effect=weighed(head)):
                self.review()
            self.lp.rnd += 1
        [item] = self.lp.state["followups"]
        self.assertIn("Commit " + "1" * 40, item)
        self.assertEqual(self.lp.state["followup_checks"], {item: "false"})
        self.assertEqual(self.lp.state["followup_commits"], {item: "1" * 40})
        # ... while another defect with the same check is another follow-up, kept beside it
        other = {"kind": "follow-up", "path": "b.py", "line": 2, "what": "zero divisor crashes",
                 "why": "callers crash", "evidence": {"run": "false", "commit": "3" * 40,
                                                     "returncode": 1, "output": ""}}
        with patch.object(run, "weigh_review",
                          return_value=hand_in.Review([other, {"kind": "done"}])):
            self.review()
        self.assertEqual(len(self.lp.state["followups"]), 2)
        self.assertTrue(any(text.startswith("b.py:2 - zero divisor crashes") for text in self.lp.state["followups"]))

    def test_a_pass_overridden_by_the_loop_keeps_its_followups_too(self):
        self.review(OTHER)
        for ok, code in ((False, 0), (True, 1)):
            with self.subTest(ok=ok, code=code):
                self.assertEqual(self.review(DEFECT, ok=ok, code=code), "FAIL")
                self.assert_followups([OTHER, DEFECT])

    def test_no_number_limit_or_cross_item_deduplication(self):
        items = [f"{DEFECT}; case {n}" for n in range(30)]
        self.review(*items)
        self.assert_followups(items)

    def test_indented_evidence_stays_with_its_item(self):
        item = ("a.py:1 - empty input crashes - rejects valid input\n\n"
                "Base abc123:\n```python\nparse([])\n```\nIndexError")
        self.review(item, OTHER)
        self.assert_followups([item, OTHER])
        self.assertIn("- " + item.replace("\n", "\n  "), run.pr_body(self.lp.state))

    def test_flaky_evidence_joins_the_passing_review_and_pr_without_shared_files(self):
        output, flake = self.gate()
        self.review(DEFECT, output=output)
        self.assert_followups([DEFECT, flake])
        url = "https://github.com/acme/project/pull/7"
        with patch.object(run, "gh", return_value=(0, url)):
            self.assertEqual(run.open_pr(self.lp, "main"), url)
        body = (self.lp.run_dir / "pr-body.md").read_text()
        self.assertIn("- " + DEFECT, body)
        self.assertIn("- " + flake.replace("\n", "\n  "), body)
        self.assertFalse((config.HOME / "followups").exists())

    def test_existing_files_and_archives_are_neither_read_nor_written(self):
        directory = config.HOME / "followups"
        directory.mkdir(parents=True)
        files = {"workspace.md": b"old follow-ups\n", "WORKSPACE.md": b"other case\n",
                 "workspace.archive.md": b"old archive\n"}
        for name, content in files.items():
            (directory / name).write_bytes(content)
        original = Path.open

        def guarded(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(directory), f"accessed {path}")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", guarded), \
                patch.object(run, "gh", return_value=(0, "https://github.com/acme/project/pull/7")):
            output, _ = self.gate()
            self.review(DEFECT, output=output)
            run.open_pr(self.lp, "main")
            self.review(OTHER, record=False)
            run.open_pr(self.lp, "main")
        self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir()}, files)
        self.assertNotIn("followups/", (REPO / "orchestrator.md").read_text())

    def test_final_check_flake_joins_the_saved_passing_review(self):
        self.review(DEFECT)
        output, flake = self.gate()
        self.lp.once = ["fixture check"]
        with patch.object(run, "git", return_value="abc123"), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(gate, "run_done_when", return_value=(True, output)):
            self.assertTrue(run.final_check(self.lp, "origin/main"))
        self.assert_followups([DEFECT, flake])
        self.assertIn(flake.replace("\n", "\n  "), run.pr_body(self.lp.state))

    def test_existing_pr_carries_the_grown_list_and_retries_a_failed_update(self):
        url = "https://github.com/acme/project/pull/7"
        self.review(DEFECT)
        with patch.object(run, "gh", return_value=(0, url)):
            run.open_pr(self.lp, "main")
        self.review(OTHER, record=False)          # the list grew: the description follows
        bodies = []

        def gh(_cwd, *args):
            # `gh pr edit` as gh 2.46 answers since GitHub retired Projects (classic): it fails
            # and changes nothing, so the description goes through the REST API
            if args[:2] == ("pr", "edit"):
                return 1, ("GraphQL: Projects (classic) is being deprecated in favor of the new "
                           "Projects experience (repository.pullRequest.projectCards)")
            self.assertEqual(args[:4], ("api", "-X", "PATCH", "repos/acme/project/pulls/7"))
            self.assertEqual(args[4], "-F")
            bodies.append(Path(args[5].removeprefix("body=@")).read_text())
            return (1, "update failed") if len(bodies) == 1 else (0, "")

        with patch.object(run, "gh", side_effect=gh):
            self.assertIsNone(run.open_pr(self.lp, "main"))
            self.assertEqual(run.open_pr(self.lp, "main"), url)
            self.assertEqual(run.open_pr(self.lp, "main"), url)
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[0], bodies[1])
        self.assertIn("## Follow-ups", bodies[1])
        self.assertIn("b.py:2 - zero divisor crashes", bodies[1])
        self.assertEqual((self.lp.run_dir / "pr-body.md").read_text(), bodies[1])


if __name__ == "__main__":
    unittest.main()
