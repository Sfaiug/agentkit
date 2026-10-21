"""An AGENTS.md body grows to 300 words at most, and past that only shrinks, in every repository."""

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
    return " ".join(f"acme{i}" for i in range(n))


class AgentsBodyOnlyShrinks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-agents-words-", dir=REPO)
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
        self.git("commit", "-q", "--allow-empty", "-m", "acme base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, text=None, path="AGENTS.md"):
        if text is not None:
            (self.repo / path).write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "acme change")
        return self.git("rev-parse", "HEAD")

    def check(self, base, body, front=None):
        """rules_check on a branch from `base` whose AGENTS.md body is `body` words."""
        self.git("checkout", "-q", "-B", "fix-api", base)
        self.commit(f"---\n{front}---\n{words(body)}\n" if front is not None else f"{words(body)}\n")
        return roundloop.rules_check(SimpleNamespace(wt=self.repo, base_sha=base, scratch=False))

    def test_a_body_past_the_floor_only_shrinks(self):
        base = self.commit(f"{words(400)}\n")
        refused = self.check(base, 401)
        self.assertIn("from 400 to 401 words", refused)
        self.assertIn("a test, a check or a comment", refused)
        self.assertEqual(self.check(base, 400), "")
        self.assertEqual(self.check(base, 120), "")

    def test_a_body_under_the_floor_grows_to_it(self):
        base = self.commit(f"{words(100)}\n")
        self.assertEqual(self.check(base, roundloop.BODY_WORDS), "")
        self.assertIn(f"from 100 to {roundloop.BODY_WORDS + 1} words",
                      self.check(base, roundloop.BODY_WORDS + 1))

    def test_a_new_file_starts_under_the_floor(self):
        base = self.commit()
        self.assertEqual(self.check(base, roundloop.BODY_WORDS), "")
        self.assertIn(f"from 0 to {roundloop.BODY_WORDS + 1}",
                      self.check(base, roundloop.BODY_WORDS + 1))

    def test_front_matter_is_not_body(self):
        base = self.commit(f"{words(roundloop.BODY_WORDS)}\n")
        self.assertEqual(self.check(base, roundloop.BODY_WORDS, front="users: none\ntests: true\n"), "")
        self.assertEqual(self.check(base, roundloop.BODY_WORDS, front=""), "")

    def test_a_branch_leaving_the_file_alone_passes(self):
        base = self.commit(f"{words(5000)}\n")
        self.git("checkout", "-q", "-B", "fix-api", base)
        self.commit("acme\n", path="api.py")
        self.assertEqual(roundloop.rules_check(SimpleNamespace(wt=self.repo, base_sha=base, scratch=False)), "")


if __name__ == "__main__":
    unittest.main()
