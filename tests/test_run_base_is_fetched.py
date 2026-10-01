"""agentkit: a new run is cut from its base as origin has it now, not from a stale local ref."""

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


class Cut(Exception):
    """The worktree is where this test stops the run: its base is decided by then."""


class RunBaseIsFetched(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-run-base-fetched-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.SESSION_ENV: "", config.RUN_DIR_ENV: "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name, value in (("disk_pressure", False), ("launch_session", None)):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        config.ensure_dirs()
        self.cfg = config.load()
        self.origin = self.root / "acme.git"
        self.repo = self.root / "acme"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.git(self.root, "clone", "-q", str(self.origin), str(self.repo))
        self.commit(self.repo, "seed")
        self.stale = self.commit(self.repo, "old")
        # someone else merges after this checkout last fetched: its `main` and `origin/main`
        # both still name `old`
        other = self.root / "other"
        self.git(self.root, "clone", "-q", str(self.origin), str(other))
        self.fresh = self.commit(other, "new")
        self.logs = []

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, cwd, message):
        self.git(cwd, "-c", "user.name=fixture", "-c", "user.email=fixture@localhost",
                 "commit", "-q", "--allow-empty", "-m", message)
        self.git(cwd, "push", "-q", "origin", "HEAD:main")
        return self.git(cwd, "rev-parse", "HEAD")

    def cut(self, base=None):
        """The commit a fresh run's worktree is made from."""
        directory = config.RUNS / f"fix-api-{base or 'default'}".replace("/", "-")
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\n" + (f"base: {base}\n" if base else "")
                        + "---\n# Fix the API\n\n## Done when\n```bash\ntrue\n```\n")
        opts = {"--rounds": "1", "--no-worktree": False, "--no-merge": True,
                "--exec": None, "--review": None}
        made = []

        def make_worktree(repo, run_id, slug, base_sha, **_kw):
            made.append(base_sha)
            raise Cut()

        with patch.object(run, "make_worktree", side_effect=make_worktree):
            with self.assertRaises(Cut):
                run.loop(self.cfg, directory, task, opts, self.logs.append)
        return made[0]

    def test_a_local_branch_behind_origin_is_cut_from_origin(self):
        self.assertEqual(self.cut("main"), self.fresh)

    def test_the_default_base_is_fetched_before_it_is_read(self):
        self.assertEqual(self.cut(), self.fresh)

    def test_a_base_on_origin_is_not_taken_for_a_branch_named_like_it(self):
        self.git(self.repo, "push", "-q", "origin", f"{self.stale}:refs/heads/origin/main")
        self.assertEqual(self.cut(), self.fresh)
        self.assertEqual(self.cut("origin/main"), self.fresh)

    def test_origin_s_branch_wins_over_a_tag_named_like_it(self):
        self.git(self.repo, "tag", "origin/main", self.stale)
        self.assertEqual(self.cut("main"), self.fresh)

    def test_offline_it_falls_back_to_the_local_ref_and_says_so(self):
        self.git(self.repo, "remote", "set-url", "origin", str(self.root / "gone.git"))
        self.assertEqual(self.cut("main"), self.stale)
        self.assertTrue(any(line.startswith("WARN git fetch origin failed; basing this run "
                                            "on the local main") for line in self.logs),
                        self.logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
