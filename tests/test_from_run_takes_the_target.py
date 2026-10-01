"""A fresh from: run takes its fetched target before round 1; a resume keeps its head.

Offline: local Git repositories and a throwaway HOME, stopping at the round boundary.
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
from agentkit import config, run


class AtRound(Exception):
    def __init__(self, lp):
        self.lp = lp


class FromRunTakesTheTarget(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-from-target-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.SESSION_ENV: "", config.RUN_DIR_ENV: "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@localhost",
            "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@localhost"}))
        for name, value in (("disk_pressure", False), ("launch_session", None),
                            ("collect_usage", {}), ("ready_order", ["opus", "astra"]),
                            ("pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        config.ensure_dirs()
        self.cfg = config.load()
        self.origin = self.root / "acme-origin"
        self.repo = self.root / "acme"
        self.git(self.root, "init", "-q", "-b", "main", str(self.origin))
        self.base = self.commit(self.origin, "shared.txt", "base\n")
        self.git(self.root, "clone", "-q", "--single-branch", str(self.origin), str(self.repo))
        self.git(self.repo, "checkout", "-qb", "ak/previous")
        self.previous = self.commit(self.repo, "carried.txt", "saved work\n")
        self.git(self.repo, "checkout", "-q", "main")
        self.logs = []

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, cwd, name, text):
        (cwd / name).write_text(text)
        self.git(cwd, "add", name)
        self.git(cwd, "commit", "-qm", "acme change")
        return self.git(cwd, "rev-parse", "HEAD")

    def start(self, target="main", prior=None):
        if prior is None:
            directory = config.RUNS / f"fix-api-{len(list(config.RUNS.iterdir()))}"
            directory.mkdir()
            task = directory / "task.md"
            task.write_text(f"---\nrepo: {self.repo}\nbase: main\ntarget: {target}\n"
                            "from: ak/previous\n---\n# Fix the API\n\n"
                            "## Done when\n```bash\ntrue\n```\n")
        else:
            directory = config.RUNS / prior["run_id"]
            task = directory / "task.md"
        opts = {"--rounds": "1", "--no-worktree": False, "--no-merge": True,
                "--exec": None, "--review": None}

        def rounds(lp, **_kw):
            raise AtRound(lp)

        with patch.object(run, "rounds", side_effect=rounds):
            with self.assertRaises(AtRound) as caught:
                run.loop(self.cfg, directory, task, opts, self.logs.append, prior)
        return caught.exception.lp

    def test_round_one_carries_the_fresh_target_and_the_saved_work(self):
        fresh = self.commit(self.origin, "fixed.txt", "target fix\n")
        self.assertEqual(self.git(self.repo, "rev-parse", "origin/main"), self.base)
        lp = self.start()
        self.assertTrue((lp.wt / "fixed.txt").is_file(), "round 1 lacks the target's fix")
        self.assertEqual((lp.wt / "fixed.txt").read_text(), "target fix\n")
        self.assertEqual((lp.wt / "carried.txt").read_text(), "saved work\n")
        self.git(lp.wt, "merge-base", "--is-ancestor", fresh, "HEAD")
        self.git(lp.wt, "merge-base", "--is-ancestor", self.previous, "HEAD")
        self.assertEqual(self.git(self.repo, "rev-parse", "ak/previous"), self.previous)
        self.assertEqual(self.git(lp.wt, "status", "--porcelain"), "")
        self.assertTrue(any("merged origin/main" in line and "round 1" in line
                            for line in self.logs), self.logs)

    def test_the_named_target_is_taken_even_with_a_single_branch_fetch_and_a_tag(self):
        self.git(self.origin, "checkout", "-qb", "dev")
        fresh = self.commit(self.origin, "fixed.txt", "dev fix\n")
        self.git(self.repo, "tag", "origin/dev", self.base)
        for target in ("dev", "origin/dev", "refs/heads/dev", "refs/remotes/origin/dev"):
            with self.subTest(target=target):
                lp = self.start(target)
                self.assertTrue((lp.wt / "fixed.txt").is_file(), "round 1 lacks dev's fix")
                self.git(lp.wt, "merge-base", "--is-ancestor", fresh, "HEAD")
                self.assertEqual((lp.wt / "fixed.txt").read_text(), "dev fix\n")
                self.assertTrue(any("merged origin/dev" in line for line in self.logs))

    def test_a_conflict_is_aborted_and_round_one_keeps_the_saved_branch(self):
        self.git(self.repo, "checkout", "-q", "ak/previous")
        previous = self.commit(self.repo, "shared.txt", "branch change\n")
        self.git(self.repo, "checkout", "-q", "main")
        fresh = self.commit(self.origin, "shared.txt", "target change\n")
        lp = self.start()
        self.assertEqual(self.git(lp.wt, "rev-parse", "origin/main"), fresh)
        self.assertEqual(self.git(lp.wt, "rev-parse", "HEAD"), previous)
        self.assertEqual(self.git(self.repo, "rev-parse", "ak/previous"), previous)
        self.assertEqual((lp.wt / "shared.txt").read_text(), "branch change\n")
        self.assertEqual(self.git(lp.wt, "status", "--porcelain"), "")
        merge_head = Path(self.git(lp.wt, "rev-parse", "--git-path", "MERGE_HEAD"))
        self.assertFalse(merge_head.exists())
        self.assertTrue(any("conflict" in line and "aborted" in line and "landing" in line
                            and "origin/main" in line for line in self.logs), self.logs)

    def test_a_resume_never_fetches_or_merges_the_target_again(self):
        self.commit(self.origin, "fixed.txt", "target fix\n")
        lp = self.start()
        head = self.git(lp.wt, "rev-parse", "HEAD")
        self.commit(self.origin, "later.txt", "later target fix\n")
        self.logs.clear()
        with patch.object(run, "fetch", side_effect=AssertionError("resume fetched")), \
                patch.object(run, "git_out", wraps=run.git_out) as commands:
            resumed = self.start(prior=run.read_state(lp.run_dir))
        self.assertEqual(self.git(resumed.wt, "rev-parse", "HEAD"), head)
        self.assertFalse((resumed.wt / "later.txt").exists())
        self.assertFalse(any(call.args[1] == "merge" for call in commands.call_args_list))
        self.assertTrue(any("resuming at round" in line for line in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
