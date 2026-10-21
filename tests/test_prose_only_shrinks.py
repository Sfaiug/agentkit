"""Prose only shrinks, in every repository: no guide, map or notes file grows, or starts.

A branch's Markdown (or reStructuredText, AsciiDoc) past what the base holds is refused,
a new file holding any words included; a root README grows to 300 words, AGENTS.md has its
own floor, and the product text the base's `content:` names grows freely.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, roundloop


def words(n):
    return " ".join(f"acme{i}" for i in range(n)) + "\n"


class ProseOnlyShrinks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-prose-words-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        for patcher in (patch.dict(os.environ, {"HOME": tmp.name, "GIT_CONFIG_GLOBAL": os.devnull,
                                                 "GIT_CONFIG_NOSYSTEM": "1"}),
                        patch.object(config, "instruction_ceiling", return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "acme")
        self.git("config", "user.email", "acme@localhost")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for path, text in files.items():
            target = self.repo / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "acme change")
        return self.git("rev-parse", "HEAD")

    def check(self, base, files):
        """rules_check on a branch from `base` that writes `files` (None deletes one)."""
        self.git("checkout", "-q", "-B", "fix-api", base)
        self.commit(files)
        return roundloop.rules_check(SimpleNamespace(wt=self.repo, base_sha=base, scratch=False))

    def test_a_prose_file_only_shrinks(self):
        base = self.commit({"docs/guide.md": words(50)})
        refused = self.check(base, {"docs/guide.md": words(51)})
        self.assertIn("docs/guide.md grows from 50 to 51 words", refused)
        self.assertIn("a test, a check or a comment", refused)
        for kept in (50, 10):
            self.assertEqual(self.check(base, {"docs/guide.md": words(kept)}), "")
        self.assertEqual(self.check(base, {"docs/guide.md": None}), "")

    def test_a_new_prose_file_holds_nothing_in_any_prose_format(self):
        base = self.commit({"api.py": "acme\n"})
        for path in ("docs/NOTES.MD", "deploy/README.md", "docs/plan.rst", "notes.adoc", "app/AGENTS.md"):
            with self.subTest(path=path):
                self.assertIn(f"{path} grows from 0 to 1 words", self.check(base, {path: words(1)}))
        self.assertEqual(self.check(base, {"api.py": words(500), "data.json": words(500)}), "")

    def test_no_name_or_link_slips_past(self):
        base = self.commit({"api.py": "acme\n"})
        self.assertIn(" guide.md grows from 0 to 3 words", self.check(base, {" guide.md": words(3)}))
        (self.repo / "guide.md").symlink_to("api.py")
        base = self.commit({})
        (self.repo / "guide.md").unlink()
        self.assertIn("guide.md grows from 1 to 3 words", self.check(base, {"guide.md": words(3)}))

    def test_a_root_readme_grows_to_300_words(self):
        base = self.commit({"api.py": "acme\n"})
        self.assertEqual(self.check(base, {"README.md": words(roundloop.README_WORDS)}), "")
        self.assertIn(f"past {roundloop.README_WORDS} words",
                      self.check(base, {"README.md": words(roundloop.README_WORDS + 1)}))

    def test_a_rename_is_a_new_file(self):
        base = self.commit({"docs/guide.md": words(50)})
        self.assertIn("docs/manual.md grows from 0 to 50 words",
                      self.check(base, {"docs/guide.md": None, "docs/manual.md": words(50)}))

    def test_the_base_content_grows_freely_and_a_branch_cannot_widen_it(self):
        base = self.commit({"AGENTS.md": "---\ncontent: site/pages/ copy.md\n---\nAcme.\n",
                            "site/pages/home.md": words(5)})
        self.assertEqual(self.check(base, {"site/pages/home.md": words(5000),
                                           "site/pages/new.md": words(800), "copy.md": words(900)}), "")
        self.assertIn("docs/guide.md grows from 0 to 9 words", self.check(base, {
            "AGENTS.md": "---\ncontent: site/pages/ copy.md docs/\n---\nAcme.\n",
            "docs/guide.md": words(9)}))


if __name__ == "__main__":
    unittest.main()
