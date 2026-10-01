"""A file both sides changed is an overlap, whatever whitespace its name begins with."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import run


class TargetDisjointNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.commit({" app.py": "base\n"})
        self.base = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")
        return self.git("rev-parse", "HEAD")

    def test_shared_name_with_a_leading_space_is_an_overlap(self):
        # sorted first only on the target's side, where `git()` stripped its space
        tip = self.commit({" app.py": "main\n"})
        self.git("checkout", "-q", "-b", "ak/fix-api", self.base)
        head = self.commit({" app.py": "task\n", " 0.md": "notes\n"})
        self.assertFalse(run.target_disjoint_from_branch(self.repo, self.base, head, tip))
        self.assertFalse(run.target_disjoint_from_branch(self.repo, self.base, tip, head))

    def test_different_files_are_still_disjoint(self):
        tip = self.commit({" docs.md": "main\n"})
        self.git("checkout", "-q", "-b", "ak/fix-api", self.base)
        head = self.commit({" app.py": "task\n"})
        self.assertTrue(run.target_disjoint_from_branch(self.repo, self.base, head, tip))


if __name__ == "__main__":
    unittest.main()
