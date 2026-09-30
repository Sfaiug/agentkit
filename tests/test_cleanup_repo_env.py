"""A repository's `cleanup:` line gets the repo's secrets, whichever removal starts it."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import config, run  # noqa: E402


class CleanupRepoEnv(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="cleanup-env-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root / "home"),
            config.SESSION_ENV: "", config.RUN_DIR_ENV: "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "ACME_DB_TOKEN"):
            os.environ.pop(name, None)
        config.ensure_dirs()
        # a fake secret in the temporary HOME, named for the repo and not the checkout
        (config.ENV / "acme.env").write_text("export ACME_DB_TOKEN='fake-token'\n")
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Cleanup test")
        self.git("config", "user.email", "cleanup@localhost")
        (self.repo / "AGENTS.md").write_text(
            f"---\ncleanup: echo \"token=$ACME_DB_TOKEN\" >> {self.root / 'seen'}\n---\n# acme\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def make_run(self, name):
        wt = config.WT / name
        branch = f"ak/{name}"
        self.git("worktree", "add", "-q", str(wt), "-b", branch)
        run_dir = config.RUNS / name
        run_dir.mkdir()
        state = {"run_id": name, "repo": str(self.repo), "worktree": str(wt),
                 "branch": branch, "state": "stopped", "verdict": "STOPPED",
                 "pid": os.getpid()}
        (run_dir / "run.json").write_text(json.dumps(state))
        (run_dir / "log.txt").write_text("")
        return wt, run_dir, state

    def seen(self):
        return (self.root / "seen").read_text().splitlines()

    def test_every_removal_path_gives_cleanup_the_repo_secrets(self):
        paths = {
            "stop": lambda wt, run_dir, state: run.stop_checkout(state, lambda message: None),
            "clean": lambda wt, run_dir, state: run.cmd_clean([state["run_id"]]),
            "sweep": lambda wt, run_dir, state: run.sweep_checkout(state, wt, lambda *a: None),
            "gc": lambda wt, run_dir, state: run.run_repo_cleanup(wt, run_dir),
        }
        for name, remove in paths.items():
            with self.subTest(path=name):
                (self.root / "seen").unlink(missing_ok=True)
                wt, run_dir, state = self.make_run(f"cleanup-{name}")
                with redirect_stdout(io.StringIO()):
                    remove(wt, run_dir, state)
                self.assertEqual(self.seen(), ["token=fake-token"])
                # the secret went to the cleanup only: a sweep over many repos never
                # hands one repo's secrets to the next one's cleanup
                self.assertNotIn("ACME_DB_TOKEN", os.environ)

    def test_unreadable_env_file_is_reported_not_silent(self):
        (config.ENV / "acme.env").write_text("not a pair\n")
        wt, run_dir, state = self.make_run("cleanup-bad-env")
        self.assertTrue(run.stop_checkout(state, lambda message: None))
        self.assertFalse(wt.exists())
        [line] = [line for line in (run_dir / "log.txt").read_text().splitlines()
                  if "repo cleanup:" in line]
        self.assertIn("not a KEY=value line", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
