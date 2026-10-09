"""Past the size ceilings, ak refuses with `split it`.

A task has at most three per-round checks (`task.MAX_CHECKS`; `# once` lines are the suite,
not checks), and a seat's own pull request gets its first review only up to 400 changed
lines (`task.MAX_PR_LINES`), generated files and pure deletions aside.  Offline: a fake
GitHub, a real checkout whose attributes mark a generated file.
"""

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, record, run, task as taskfile

URL = "https://github.com/acme/widget/pull/7"
INFO = {"number": 7, "title": "Widget", "body": "", "author": "acme-bot", "baseRefName": "main",
        "headRefOid": "a" * 40, "url": URL, "state": "OPEN", "isDraft": False}


def changed(name, additions, deletions=0, status="modified"):
    return {"filename": name, "status": status, "additions": additions, "deletions": deletions}


class SizeGate(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "orchestrator", config.SESSION_ENV: "fix-api",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / ".gitattributes").write_text("dist/* linguist-generated\n")
        self.files = []

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def gh_json(self, _cwd, *args, **_kw):
        """GitHub's files listing, a hundred to the page."""
        page = int(args[1].rpartition("page=")[2])
        return self.files[(page - 1) * 100:page * 100], ""

    def test_a_task_has_at_most_three_per_round_checks(self):
        self.assertIsNone(taskfile.launch_refusal({}, ["true", "true", "true"]))
        self.assertIsNone(taskfile.launch_refusal({}, ["true", "true", "true", "bash tests/smoke.sh  # once"]))
        self.assertEqual(taskfile.launch_refusal({}, ["true"] * 4),
                         "4 done-when checks: a task has at most 3, one behaviour a reviewer holds "
                         "in one read; split it")

    def test_the_lines_a_review_reads_leave_out_generated_files_and_deletions(self):
        self.files = [changed("api.py", 150, 50), changed("dist/app.js", 5000, 5000),
                      changed("old.py", 0, 900, status="removed")]
        big = {**INFO, "additions": 5150, "deletions": 5950}      # GitHub's own totals
        with patch.object(run, "gh_json", side_effect=self.gh_json), \
                patch.object(run, "checkout_for", return_value=self.repo):
            self.assertEqual(run.pr_changed_lines(self.repo, "acme", "widget", 7), 200)
            self.assertIsNone(run.pr_size_refusal(big, "acme", "widget", 7, lambda _: None))
            self.files = [changed(f"src/f{n}.py", 1) for n in range(401)]   # five pages of files
            self.assertEqual(run.pr_changed_lines(self.repo, "acme", "widget", 7), 401)
            self.assertEqual(run.pr_size_refusal({**INFO, "additions": 401}, "acme", "widget", 7, lambda _: None),
                             "PR #7 changes 401 lines (generated files and pure deletions aside): "
                             "a first review takes at most 400; split it")
            # totals within the ceiling settle it with no file read at all
            with patch.object(run, "pr_changed_lines", side_effect=AssertionError("counted")):
                self.assertIsNone(run.pr_size_refusal({**INFO, "additions": 300, "deletions": 100},
                                                      "acme", "widget", 7, lambda _: None))

    def test_an_own_prs_first_review_is_refused_past_the_ceiling(self):
        self.files = [changed("api.py", 300, 101)]
        directory = config.RUNS / "20260102-0900-review-pr-widget-7"
        directory.mkdir(parents=True)
        record.save_state(directory, {"run_id": directory.name, "launched_session": "fix-api",
                                      "state": "queued"})
        logs = []
        with patch.object(run, "pr_view", return_value={**INFO, "additions": 300, "deletions": 101}), \
                patch.object(run, "own_pr_orchestrator", return_value=(True, "opus")), \
                patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "gh_json", side_effect=self.gh_json):
            with self.assertRaises(config.Error) as refused:
                run.preflight(directory, {"--review-pr": URL, "--no-merge": False}, logs.append)
            self.assertIn("PR #7 changes 401 lines", str(refused.exception))
            self.assertIn("split it", str(refused.exception))
            # somebody else's PR is reviewed whatever its size: one review, no split to ask for
            with patch.object(run, "own_pr_orchestrator", return_value=(False, None)), \
                    patch.object(run, "pr_changed_lines", side_effect=AssertionError("counted")):
                run.preflight(directory, {"--review-pr": URL, "--no-merge": False}, logs.append)


if __name__ == "__main__":
    unittest.main(verbosity=2)
