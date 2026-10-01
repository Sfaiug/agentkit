"""A task whose `repo:` names a home this host does not have is refused at launch.

`~name/...` for a user with no home cannot be expanded: pathlib raises a RuntimeError that
nothing up the stack expects.  `ak run` refuses such a task in one line naming the value
before any receipt is written, and a receipt already on disk with one belongs to no project,
so later launches from its seat, the menu's filing and the `ak watch` tick carry on.
"""

from contextlib import chdir, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, job as jobs, menu, orch, run, watch
from agentkit import record

BAD = "~nosuch-acme-owner/acme"


class RepoLineBadHome(Sandbox):
    def setUp(self):
        super().setUp()
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)     # Sandbox's patch.dict puts them back
        self.stack.enter_context(patch.object(config, "JOBS", self.root / "jobs"))
        self.stack.enter_context(patch.dict(os.environ, {
            config.RUN_DIR_ENV: "", config.SESSION_ENV: "fix-api", "AK_RUN_DEPTH": "0"}))
        self.acme = self.checkout("acme")
        config.save_session(self.cfg, "fix-api", "fable", ["opus"],
                            {"cwd": str(config.CODE), "repo": None})
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[{
            "name": "fix-api", "path": str(config.CODE), "created": 9000, "attached": False,
            "exited": False, "legacy": False, "resumable": False}]))

    def checkout(self, name):
        checkout = config.CODE / name
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m",
                        "fixture"], check=True)
        return checkout

    def task(self, path, repo):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nrepo: {repo}\n---\n# Fix the API\n\n"
                        "## Done when\n```bash\ntrue\n```\n")
        return path

    def waiting(self, name, repo):
        """A receipt as a launch that died in preflight left it: queued, no `project`."""
        directory = config.RUNS / name
        self.task(directory / "task.md", repo)
        record.save_state(directory, {"run_id": name, "state": "queued", "slot_waiting": True,
                                   "launched_session": "fix-api", "started_at": 9000,
                                   "queued_at": 9000, **record.process_owner()})
        return record.read_state(directory)

    def repo(self):
        return config.load_session(self.cfg, "fix-api")["repo"]

    def test_a_launch_is_refused_before_any_receipt(self):
        bad = self.task(self.root / "fix-api.md", BAD)
        good = self.task(self.root / "fix-docs.md", self.acme)
        for argv in ([str(bad)], [str(good), str(bad)]):
            with self.subTest(argv=len(argv)), patch.object(run, "drive", return_value=0), \
                    patch.object(jobs, "run_job_loop", return_value=0):
                with self.assertRaises(config.Error) as refused:
                    run.main(argv)
                self.assertIn(f"repo {BAD}", str(refused.exception))
                self.assertNotIn("\n", str(refused.exception))
                self.assertEqual(list(config.RUNS.iterdir()), [])
                self.assertFalse(config.JOBS.exists())
        # the loop's own read of it, for a run whose receipt came before this refusal
        with self.assertRaisesRegex(config.Error, f"repo {BAD}"):
            run.task_repo({"repo": BAD}, bad)

    def test_a_receipt_naming_one_has_no_project_and_breaks_nothing(self):
        broken = self.waiting("q0", BAD)
        self.waiting("q1", self.acme)
        orch.file_projectless(orch.listing(), [state for _, state in menu.run_records()])
        self.assertEqual(self.repo(), str(self.acme))
        config.update_session("fix-api", repo=None)
        watch.revive_seats(self.cfg, lambda _: None)
        self.assertEqual(self.repo(), str(self.acme))
        # a later launch from the same seat reads the seat's runs to file it, and goes on
        config.update_session("fix-api", repo=None)
        directory = config.RUNS / "q2"
        self.task(directory / "task.md", self.acme)
        opts = {"--no-merge": False, "--no-worktree": False, "--anyway": False, "--bg": False}
        with chdir(self.root), patch.dict(os.environ, {"AK_MAX_RUNS": "4"}), \
                patch.object(run, "refresh_seat_tally"), redirect_stdout(io.StringIO()):
            run.prepare(directory, opts, lambda _: None)
        self.assertEqual(record.read_state(directory)["state"], "queued")
        self.assertEqual(run.run_project(record.read_state(directory)), self.acme)
        self.assertIsNone(run.run_project(broken))


if __name__ == "__main__":
    unittest.main(verbosity=2)
