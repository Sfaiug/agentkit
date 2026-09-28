"""The leftover sweep leaves run locks and dependency trees out of real commits. Offline."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run


class LeftoverJunk(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".no-sandbox-commit-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"HOME": str(self.root),
                                      "GIT_CONFIG_GLOBAL": os.devnull,
                                      "GIT_CONFIG_NOSYSTEM": "1",
                                      "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"})
        env.start()
        self.addCleanup(env.stop)
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(key, None)

    def repo(self):
        repo = Path(tempfile.mkdtemp(dir=self.root))
        run.git(repo, "init", "-b", "main")
        run.git(repo, "config", "user.name", "fixture")
        run.git(repo, "config", "user.email", "fixture@localhost")
        (repo / "app.py").write_text("value = 1\n")
        run.git(repo, "add", ".")
        run.git(repo, "commit", "-m", "baseline")
        return repo

    def assert_swept(self, repo, junk, expected=("app.py",), artifacts=()):
        logs = []
        run.commit_leftovers(repo, logs.append, set(artifacts))
        self.assertEqual(run.git(repo, "diff-tree", "--no-commit-id", "--name-only",
                                 "-r", "HEAD").splitlines(), sorted(expected))
        lines = [line for line in logs if "untracked sandbox files uncommitted" in line]
        self.assertEqual(lines, [f"left {len(junk)} untracked sandbox files uncommitted: "
                                 + ", ".join(sorted(junk)[:3])])

    def test_locks_and_dependency_trees_ignore_git_rules_and_staging(self):
        cases = [(name, "file") for name in ("recovery.lock", "delivery.lock")]
        cases += [(name, kind) for name in ("node_modules", "venv", ".venv")
                  for kind in ("directory", "symlink", "dangling")]
        for prefix in ("", "packages/acme/"):
            for name, kind in cases:
                for mode in ("untracked", "ignored", "negated", "staged", "tracked"):
                    with self.subTest(prefix=prefix, name=name, kind=kind, mode=mode):
                        repo = self.repo()
                        path = repo / prefix / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if kind in ("symlink", "dangling"):
                            target = self.root / "environment"
                            target.mkdir(exist_ok=True)
                            path.symlink_to(target if kind == "symlink" else target / "gone")
                        else:
                            if kind == "directory":
                                path = path / "lib" / "dependency.py"
                                path.parent.mkdir(parents=True)
                            path.write_text("junk\n")
                        relative = path.relative_to(repo).as_posix()
                        if mode == "tracked":
                            run.git(repo, "add", "--", relative)
                            run.git(repo, "commit", "-m", "existing junk")
                            if path.is_symlink():
                                path.unlink()
                                path.symlink_to(self.root / "other-environment")
                            else:
                                path.write_text("changed junk\n")
                        if mode in ("ignored", "negated", "staged"):
                            (repo / ".git" / "info" / "exclude").write_text(name + "\n")
                            pattern = (f"!{name}\n!{name}/**\n" if mode == "negated"
                                       else name + "\n")
                            (repo / ".gitignore").write_text(pattern)
                            run.git(repo, "add", ".gitignore")
                            run.git(repo, "commit", "-m", "ignore rules")
                        if mode == "staged":
                            run.git(repo, "add", "-f", "--", relative)
                        index = run.git(repo, "ls-files", "--stage", "--", relative)
                        (repo / "app.py").write_text("value = 2\n")
                        self.assert_swept(repo, [relative])
                        self.assertTrue(path.exists() or path.is_symlink())
                        self.assertEqual(run.git(repo, "ls-files", "--stage", "--", relative),
                                         index)

    def test_untracked_dependency_symlink_is_not_readded(self):
        for name in ("node_modules", "venv", ".venv"):
            with self.subTest(name=name):
                repo = self.repo()
                (repo / name).symlink_to(self.root)
                run.git(repo, "add", name)
                run.git(repo, "commit", "-m", "existing environment link")
                run.git(repo, "rm", "--cached", name)
                (repo / "app.py").write_text("value = 2\n")
                self.assert_swept(repo, [name])
                self.assertEqual(run.git(repo, "ls-files", "--", name), "")
                self.assertEqual(run.git(repo, "diff", "--cached", "--name-status"),
                                 "D\t" + name)
                self.assertTrue((repo / name).is_symlink())

    def test_only_junk_makes_no_commit(self):
        repo = self.repo()
        before = run.git(repo, "rev-parse", "HEAD")
        for name in ("recovery.lock", "delivery.lock"):
            (repo / name).write_text("")
        (repo / "venv").symlink_to(self.root)
        logs = []
        run.commit_leftovers(repo, logs.append, set())
        self.assertEqual(run.git(repo, "rev-parse", "HEAD"), before)
        self.assertEqual(logs, ["left 3 untracked sandbox files uncommitted: "
                                "delivery.lock, recovery.lock, venv"])

    def test_other_work_commits_and_artifacts_stay_out(self):
        repo = self.repo()
        (repo / "app.py").unlink()
        files = ("feature.py", "package-lock.json", "poetry.lock", "recovery.lock.txt",
                 "src/venv.py", "venv-template/keep", "src/.phone-keep/note.txt")
        for name in files:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("real work\n")
        (repo / "source-link").symlink_to("src")
        (repo / "generated.txt").write_text("done-when artifact\n")
        (repo / "delivery.lock").write_text("")
        run.git(repo, "add", "feature.py")
        self.assert_swept(repo, ["delivery.lock"], ("app.py", "source-link", *files),
                          artifacts=("generated.txt",))
        self.assertEqual(run.git(repo, "ls-files", "--", "generated.txt"), "")


if __name__ == "__main__":
    unittest.main()
