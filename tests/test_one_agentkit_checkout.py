"""agentkit has one checkout and one project: ~/agentkit, never a second clone under ~/code.

Offline, with invented checkouts and seat records under a temporary HOME.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, orch, run
from agentkit import record


class OneAgentkitCheckout(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: "fix-api"}))
        config.save_session(self.cfg, "fix-api", "fable", ["opus"],
                            {"cwd": str(config.CODE), "repo": None})
        self.own = self.clone(Path.home() / "agentkit", "https://github.com/someone/agentkit.git")
        self.acme = self.clone(config.CODE / "acme", "git@github.com:someone/acme.git")

    def clone(self, path, origin):
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
        return path

    def test_review_finds_agentkits_own_checkout_and_clones_nothing(self):
        with patch.object(run, "gh", side_effect=AssertionError("cloned")):
            self.assertEqual(run.checkout_for("someone/agentkit", print), self.own)
            self.assertEqual(run.checkout_for("someone/acme", print), self.acme)
        self.assertFalse((config.CODE / "agentkit").exists())

    def test_a_second_clone_under_code_is_agentkits_own(self):
        clone = self.clone(config.CODE / "agentkit", "https://github.com/someone/agentkit.git")
        (clone / "agentkit").mkdir()
        self.assertEqual([path for path in orch.checkouts() if path.name == "agentkit"], [self.own])
        self.assertEqual(run.checkout_for("someone/agentkit", print), self.own)
        for value in ("agentkit", str(clone)):
            with self.subTest(checkout=value), redirect_stdout(io.StringIO()):
                self.assertEqual(orch.main(["project", value]), 0)
                self.assertEqual(config.load_session(self.cfg, "fix-api")["repo"], str(self.own))
        self.assertEqual(orch.checkout_of(clone), self.own)
        self.assertEqual(orch.cwd_project(clone / "agentkit"), self.own)
        self.assertEqual(orch.cwd_project(self.acme), self.acme)
        self.assertEqual(run.task_project(None, str(config.HOME / "tasks/agentkit/01.md")), self.own)
        directory = config.RUNS / "first"
        directory.mkdir()
        record.save_state(directory, {"run_id": "first", "launched_session": "fix-api",
                                   "state": "queued", "project": str(clone)})
        self.assertEqual(run.join_session_project("fix-api"), str(self.own))


if __name__ == "__main__":
    unittest.main(verbosity=2)
