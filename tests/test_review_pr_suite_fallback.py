"""A reviewed PR whose own branch declares no `tests:` defers its target branch's suite.

Offline: a temporary acme repository whose `origin/main` declares the suite and whose PR
head does not; GitHub, the reviewer and the merge checks are fakes.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import gate as check_gate, config, gc, run, worker
from agentkit import record as run_record

SUITE = "test -f AGENTS.md"


class ReviewPrSuiteFallback(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-review-pr-suite-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "", config.RUN_DIR_ENV: "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Suite test")
        self.git("config", "user.email", "suite@localhost")
        self.logs, self.gates, self.reviews = [], [], []
        for module, name, value in ((gc, "disk_pressure", False), (run, "launch_session", None),
                                    (run, "collect_usage", {}), (run, "post_review", True),
                                    (run, "checks", (False, "fixture: no merge"))):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.worker)))
        gate = check_gate.run_done_when

        def record(cmds, cwd, log_path, *args, **kwargs):
            self.gates.append(list(cmds))
            return gate(cmds, cwd, log_path, *args, **kwargs)
        self.stack.enter_context(patch.object(check_gate, "run_done_when", side_effect=record))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, agents):
        (self.repo / "AGENTS.md").write_text(agents)
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def worker(self, cfg, name, body, workspace, out_dir, role, session, **kwargs):
        self.reviews.append(body)
        text = "VERDICT: PASS\n## Findings\n- none"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, "fixture-session", False

    def review(self, target, head):
        """Review a PR at `head` whose target branch `origin/main` is at `target`."""
        self.git("update-ref", "refs/remotes/origin/main", target)
        directory = config.RUNS / "pr-review"
        directory.mkdir()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Mend the fence", "author": "fixture", "body": "Fixture PR"}
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "gh_json", return_value=(info, "")):
            state = run.review_pr(self.cfg, directory, "https://github.com/acme/acme/pull/1",
                                  {"--review": None, "--review-pr": "x"}, self.logs.append)
        self.assertEqual(state["state"], "pass", self.logs)
        return (directory / "task.md").read_text()

    def test_pr_without_tests_defers_the_target_suite(self):
        target = self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        head = self.commit("# acme\n\nNo front matter here.\n")
        task = self.review(target, head)
        self.assertEqual(self.gates, [], self.logs)
        self.assertIn(f"```bash\n{SUITE}  # once\n```", task)

    def test_neither_declaring_runs_nothing_and_says_so(self):
        target = self.commit("# acme\n")
        head = self.commit("# acme\n\nNo front matter here.\n")
        task = self.review(target, head)
        self.assertEqual(self.gates, [], self.logs)
        self.assertIn("true   # AGENTS.md declares no tests:", task)
        self.assertTrue(self.reviews)
        self.assertIn("nothing was run", self.reviews[-1])
        # nothing ran, so nothing passed: the record and the report say so, and the PASS stands
        state = run_record.read_state(config.RUNS / "pr-review")
        self.assertIsNone(state["round_summaries"][-1]["done_when"])
        self.assertIsNone(state["review"]["done_when"])
        self.assertTrue(run.review_pass(state, self.cfg))
        result = (config.RUNS / "pr-review" / "result.md").read_text()
        self.assertIn("## Round 1 (PASS, done-when not run)", result)
        self.assertNotIn("done-when passed", result)


if __name__ == "__main__":
    unittest.main()
