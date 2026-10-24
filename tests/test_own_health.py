"""agentkit's own change is live once the checkout it merged into has installed it.

The tick moves that checkout only to a commit whose tests/live.sh passed (`update.go_live`), so
a merged change of ak's waits there; this `health:` makes that wait ak's own step, which the
stop hook and the seat's word read (`watch.awaiting_live`), and one still not installed when
the window closes is told as broken.

Offline: a temporary repository and the tick's own probe.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall, watch


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class OwnHealth(unittest.TestCase):
    def test_live_once_the_merge_is_installed(self):
        command = gitcall.front_value((REPO / "AGENTS.md").read_text(), "health")
        self.assertTrue(command, "AGENTS.md declares no health:")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env = {**os.environ, "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@example.com",
                   "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@example.com"}
            subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
            for message in ("installed", "merged"):
                subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty",
                                "-m", message], check=True, env=env)
            merged = git(repo, "rev-parse", "HEAD")
            git(repo, "checkout", "-q", "--detach", "HEAD~1")
            self.assertFalse(watch.health_command(repo, merged, command)[0],
                             "a merge the checkout has not installed reads live")
            git(repo, "checkout", "-q", "--detach", merged)
            passed, output = watch.health_command(repo, merged, command)
            self.assertTrue(passed, output)


if __name__ == "__main__":
    unittest.main()
