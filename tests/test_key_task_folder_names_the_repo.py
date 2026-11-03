"""A task's repo line, task folder, then launch directory choose where it runs.

Black-box through AK_BIN and fixtures/akbin.py: a task filed under tasks/acme/
launches inside other, and its saved repository and real worktree agree.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class TaskFolderNamesTheRepo(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.acme = Rig(self.home, "acme")
        self.other = Rig(self.home, "other")
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="work", codex="pass")

    def launch(self, repo=None, folder="acme"):
        source = taskfile.write(self.home, repo)
        task = self.home.write(f".agentkit/tasks/{folder}/fix-api.md", source.read_text())
        done = self.home.ak("run", str(task), "--no-merge", cwd=self.other.path, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        directory = taskfile.only_run(self.home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(state["task_file"], str(task))
        self.assertTrue((Path(state["worktree"]) / "retry.txt").is_file())
        # A status read from elsewhere keeps the repository chosen at launch.
        shown = self.home.ak("run", "status", "--json", cwd=self.home.path)
        self.assertEqual(shown.code, 0, shown.out + shown.err)
        row = next(row for row in json.loads(shown.out) if row["run_id"] == directory.name)
        self.assertEqual(row["repo"], state["repo"])
        return state

    def assert_repo(self, state, repo):
        self.assertEqual(state["repo"], str(repo.path))
        self.assertFalse(state["scratch"])
        common = self.home.run("git", "rev-parse", "--git-common-dir", cwd=state["worktree"])
        self.assertEqual(common.code, 0, common.err)
        self.assertEqual(Path(common.out.strip()).resolve(), repo.path / ".git")

    def test_task_folder_wins_over_the_launch_checkout(self):
        self.assert_repo(self.launch(), self.acme)

    def test_explicit_repo_wins_over_the_task_folder(self):
        self.assert_repo(self.launch(self.other.path), self.other)

    def test_unknown_task_folder_falls_back_to_the_launch_checkout(self):
        self.assert_repo(self.launch(folder="nowhere"), self.other)

    def test_explicit_none_keeps_the_run_scratch(self):
        state = self.launch("none")
        self.assertIsNone(state["repo"])
        self.assertTrue(state["scratch"])
        self.assertFalse((Path(state["worktree"]) / ".git").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
