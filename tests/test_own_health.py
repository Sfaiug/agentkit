"""agentkit's own change is live once the checkout it merged into has installed it.

The tick moves that checkout only to a commit whose tests/live.sh passed (`update.go_live`), so
a merged change of ak's waits there; this `health:` makes that wait ak's own step, which the
stop hook and the seat's word read (`watch.awaiting_live`), and one still not installed when
the window closes is told as broken.

Offline: a temporary repository and the tick's own probe.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall, watch


class OwnHealth(unittest.TestCase):
    def test_live_once_the_merge_is_installed(self):
        command = gitcall.front_value((REPO / "AGENTS.md").read_text(), "health")
        self.assertTrue(command, "AGENTS.md declares no health:")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            for message in ("installed", "merged"):
                subprocess.run(["git", "-C", str(repo), "-c", "user.name=acme", "-c",
                                "user.email=acme@example.com", "commit", "-q", "--allow-empty",
                                "-m", message], check=True)
            merged = gitcall.git(repo, "rev-parse", "HEAD")
            gitcall.git(repo, "checkout", "-q", "--detach", "HEAD~1")
            self.assertFalse(watch.health_command(repo, merged, command)[0],
                             "a merge the checkout has not installed reads live")
            gitcall.git(repo, "checkout", "-q", "--detach", merged)
            passed, output = watch.health_command(repo, merged, command)
            self.assertTrue(passed, output)


if __name__ == "__main__":
    unittest.main()
