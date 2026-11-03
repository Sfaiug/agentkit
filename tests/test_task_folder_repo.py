"""A task with no `repo:` prefers its task folder's checkout to the launch checkout."""

from contextlib import chdir
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run


class TaskFolderRepo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-task-folder-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.code = self.root / "code"
        self.acme = self.checkout(self.code / "acme")
        self.other = self.checkout(self.code / "other")
        home = patch.object(config, "HOME", self.root / "home")
        home.start()
        self.addCleanup(home.stop)
        known = patch.object(orch, "checkouts", return_value=[self.acme, self.other])
        known.start()
        self.addCleanup(known.stop)
        ceiling = patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root)})
        ceiling.start()
        self.addCleanup(ceiling.stop)
        self.task = config.HOME / "tasks" / "Acme" / "fix-api.md"
        self.task.parent.mkdir(parents=True)
        self.task.write_text("# Fix API\n")

    def checkout(self, path):
        subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
        return path

    def test_outside_any_checkout_the_task_folder_names_the_repo(self):
        with chdir(self.code):
            self.assertEqual(run.task_repo({}, self.task), self.acme)

    def test_inside_a_checkout_the_task_folder_still_wins(self):
        with chdir(self.other):
            self.assertEqual(run.task_repo({}, self.task), self.acme)

    def test_the_original_task_file_names_the_repo_for_a_run_copy(self):
        with chdir(self.other):
            self.assertEqual(run.task_repo({}, self.root / "task.md", self.task), self.acme)

    def test_a_task_filed_under_no_known_checkout_stays_scratch(self):
        loose = config.HOME / "tasks" / "nowhere" / "fix-api.md"
        loose.parent.mkdir(parents=True)
        loose.write_text("# Fix API\n")
        outside = self.root / "plain.md"
        outside.write_text("# Fix API\n")
        with chdir(self.code):
            self.assertIsNone(run.task_repo({}, loose))
            self.assertIsNone(run.task_repo({}, outside))
            self.assertIsNone(run.task_repo({"repo": "none"}, self.task))
        with chdir(self.other):
            self.assertEqual(run.task_repo({}, loose), self.other)
            self.assertEqual(run.task_repo({}, outside), self.other)
            self.assertEqual(run.task_repo({"repo": str(self.other)}, self.task), self.other)
            self.assertIsNone(run.task_repo({"repo": "none"}, self.task))


if __name__ == "__main__":
    unittest.main()
