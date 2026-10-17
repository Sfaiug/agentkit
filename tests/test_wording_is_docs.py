"""Only documents people read skip review as wording.

A seat's own PR that touches nothing but wording skips the reviewer.  Wording used to be any
Markdown or translation file, so a product's own knowledge (an assistant that reads a folder
of Markdown as everything it knows) and the rulebook a model works by skipped review too.
Now a document is a README, CHANGELOG, LICENSE, ARCHITECTURE or the like at any depth, or
prose under the top-level `docs/`; every other file is reviewed.

Offline: a throwaway Git repository with invented names and a temporary HOME.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import deliver

DOCUMENTS = ("README.md", "pkg/README.rst", "CHANGELOG", "LICENSE.txt", "ARCHITECTURE.md",
             "docs/guide.md", "docs/deep/notes.txt")
REVIEWED = ("data/acme_help/billing.md", "orchestrator.md", "notes.md", "locale/de.po",
            "app.xlf", "docs/Makefile", "docs/build.sh", "pkg/docs/guide.md", "docs/AGENTS.md")


class WordingIsDocs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-wording-")
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        env = patch.dict(os.environ, {"HOME": tmp.name, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.repo / "app.py").write_text("print('acme')\n")
        self.commit("Fixture base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def touches(self, name):
        """Does a commit changing only `name` skip review?"""
        base = self.git("rev-parse", "HEAD")
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"words for {name}\n")
        return deliver.text_only_pr(self.repo, base, self.commit(f"Fixture changes {name}"))

    def test_a_document_people_read_skips_review(self):
        for name in DOCUMENTS:
            with self.subTest(name=name):
                self.assertTrue(self.touches(name))

    def test_markdown_a_product_or_model_reads_and_translations_are_reviewed(self):
        for name in REVIEWED:
            with self.subTest(name=name):
                self.assertFalse(self.touches(name))

    def test_one_reviewed_file_among_documents_is_reviewed(self):
        base = self.git("rev-parse", "HEAD")
        for name in ("README.md", "docs/guide.md", "data/acme_help/billing.md"):
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text("words\n")
        self.assertFalse(deliver.text_only_pr(self.repo, base, self.commit("Fixture mixes")))


if __name__ == "__main__":
    unittest.main()
