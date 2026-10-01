"""A live update whose install.sh failed is retried by the next tick until it passes.

The pull already moved HEAD to origin's main, so the tick has nothing to pull: it runs
install.sh again for the code checked out, says the failure once, and says the pass.

Offline throughout: origin is a throwaway bare repository, ~/agentkit is its clone under a
temporary HOME, and install.sh is a fake committed there that fails while `broken` sits beside
the clone.  The real ~/agentkit and its origin are never read or written here.
"""

from contextlib import ExitStack
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update

INSTALL = ('#!/bin/sh\necho installed >>"$(dirname "$0")/../installs"\n'
           '[ ! -e "$(dirname "$0")/../broken" ] || { echo broken; exit 3; }\n')


def git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


class GoLiveRetriesInstall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-go-live-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}))
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        origin, seed, self.clone = self.root / "origin.git", self.root / "seed", self.root / "agentkit"
        stack.enter_context(patch.object(config, "REPO", self.clone))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                       check=True, timeout=60)
        subprocess.run(["git", "clone", "-q", str(origin), str(seed)],
                       check=True, capture_output=True, timeout=60)
        git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
        (seed / "install.sh").write_text(INSTALL)
        (seed / "install.sh").chmod(0o755)
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "first")
        git(seed, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(origin), str(self.clone)],
                       check=True, capture_output=True, timeout=60)
        (seed / "notes").write_text("second\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "second")
        git(seed, "push", "-q", "origin", "main")
        self.new = git(seed, "rev-parse", "HEAD")

    def installs(self):
        path = self.root / "installs"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def tick(self):
        """One tick's go_live: what it logged, and the commands it ran."""
        said = []
        with patch.object(update.subprocess, "run", wraps=subprocess.run) as ran:
            update.go_live(said.append)
        return said, [call.args[0] for call in ran.call_args_list]

    def test_a_failed_install_is_retried_without_a_pull_until_it_passes(self):
        (self.root / "broken").write_text("")
        said, _ = self.tick()
        self.assertEqual(said[0], f"WARN agentkit did not go live at {self.new[:12]}:")
        self.assertIn("  broken", said)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.new)
        self.assertEqual(self.installs(), 1)
        said, ran = self.tick()                  # retried, not said again, nothing pulled
        self.assertEqual(said, [])
        self.assertEqual(self.installs(), 2)
        self.assertFalse([cmd for cmd in ran if "pull" in cmd], ran)
        (self.root / "broken").unlink()
        said, ran = self.tick()                  # the retry that passes says so
        self.assertEqual(said, [f"agentkit is live at {self.new[:12]}"])
        self.assertEqual(self.installs(), 3)
        self.assertFalse([cmd for cmd in ran if "pull" in cmd], ran)
        self.assertEqual(self.tick()[0], [])     # passed: no further install
        self.assertEqual(self.installs(), 3)


if __name__ == "__main__":
    unittest.main()
