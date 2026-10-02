"""Only the last passing review and flaky check evidence survive as run follow-ups.

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
from fixtures.hand_in import records, submitting
from agentkit import config, hand_in, run, worker

DEFECT = "a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError"
OTHER = "b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"


class FollowupRule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-followup-rule-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(run, "review_providers", return_value=("a", "b")))
        self.stack.enter_context(patch.object(run, "history_role_tokens"))
        self.stack.enter_context(patch.object(run.history, "update_run"))
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        directory = config.RUNS / "followup-fixture"
        directory.mkdir(parents=True)
        state = {"run_id": directory.name, "title": "Follow-up fixture", "state": "running",
                 "base": "origin/main", "base_sha": "abc123", "branch": "ak/fix-api",
                 "rounds": 3, "round_summaries": [], "executor": "executor",
                 "reviewer": "reviewer", "scratch": True, "repo": str(self.workspace),
                 "worktree": str(self.workspace)}
        self.lp = run.Loop({}, directory, state, {}, lambda _: None, self.workspace,
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
        ok, output = run.run_done_when([command], self.workspace,
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
        self.assertEqual(run.read_state(self.lp.run_dir)["followups"], items)

    def test_every_reviewer_uses_the_same_proven_preexisting_defect_rule(self):
        for role, preamble in worker.PREAMBLES.items():
            if not role.startswith("reviewer"):
                continue
            with self.subTest(role=role):
                self.assertIn(worker.GATE, preamble)
                for words in ("of a kind that would fail a round, with that same evidence",
                              "existed before this task",
                              "prove that by naming the base commit or quoting main as it was before the task",
                              "Hand in only these with `ak hand-in follow-up`",
                              "Omit everything else everywhere",
                              "however long the follow-ups list is"):
                    self.assertIn(words, preamble)

    def test_failed_reviews_and_their_flakes_are_not_carried_into_pass(self):
        output, _ = self.gate()
        self.assertEqual(self.review(DEFECT, verdict="FAIL", output=output), "FAIL")
        self.assert_followups([])
        self.lp.rnd += 1
        self.assertEqual(self.review(OTHER), "PASS")
        self.assert_followups([OTHER])

    def test_re_review_replaces_a_previous_pass_including_an_empty_list(self):
        self.review(DEFECT, OTHER)
        self.assert_followups([DEFECT, OTHER])
        updated = DEFECT + "; also reproduced on main before the task"
        self.review(updated, record=False)
        self.assert_followups([updated])
        self.review(record=False)
        self.assert_followups([])
        self.assertNotIn("## Follow-ups", run.pr_body(self.lp.state))

    def test_a_pass_overridden_by_the_loop_keeps_no_followups(self):
        for ok, code in ((False, 0), (True, 1)):
            with self.subTest(ok=ok, code=code):
                self.lp.state["followups"] = [OTHER]
                self.assertEqual(self.review(DEFECT, ok=ok, code=code), "FAIL")
                self.assert_followups([])

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
                patch.object(run, "run_done_when", return_value=(True, output)):
            self.assertTrue(run.final_check(self.lp, "origin/main"))
        self.assert_followups([DEFECT, flake])
        self.assertIn(flake.replace("\n", "\n  "), run.pr_body(self.lp.state))

    def test_existing_pr_drops_the_old_list_and_retries_a_failed_update(self):
        url = "https://github.com/acme/project/pull/7"
        self.review(DEFECT)
        with patch.object(run, "gh", return_value=(0, url)):
            run.open_pr(self.lp, "main")
        self.review(record=False)
        bodies = []

        def gh(_cwd, *args):
            self.assertEqual(args[:4], ("pr", "edit", url, "--body-file"))
            bodies.append(Path(args[4]).read_text())
            return (1, "update failed") if len(bodies) == 1 else (0, "")

        with patch.object(run, "gh", side_effect=gh):
            self.assertIsNone(run.open_pr(self.lp, "main"))
            self.assertEqual(run.open_pr(self.lp, "main"), url)
            self.assertEqual(run.open_pr(self.lp, "main"), url)
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[0], bodies[1])
        self.assertNotIn("## Follow-ups", bodies[1])
        self.assertEqual((self.lp.run_dir / "pr-body.md").read_text(), bodies[1])


if __name__ == "__main__":
    unittest.main()
