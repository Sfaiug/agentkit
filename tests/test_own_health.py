"""agentkit's own change is live once this host's installation, ~/agentkit, holds it and its
install.sh has passed.

The tick moves ~/agentkit only to a commit whose tests/live.sh passed (`update.go_live`) and
keeps `agentkit-install-pending` until install.sh passes (`update.update_agentkit`), so a merged
change of ak's waits there; this `health:` makes that wait ak's own step, which the stop hook
and the seat's word read (`watch.awaiting_live`), and one still not installed when the window
closes is told as broken.  The run's own checkout says nothing: it may be any source checkout.

Offline: a temporary HOME and the tick's own probe.
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
from agentkit import config, gitcall, watch


class OwnHealth(unittest.TestCase):
    def test_live_once_this_host_installed_the_merge(self):
        command = gitcall.front_value((REPO / "AGENTS.md").read_text(), "health")
        self.assertTrue(command, "AGENTS.md declares no health:")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}), \
                patch.object(config, "HOME", Path(tmp) / ".agentkit"):
            installed, source = Path(tmp) / "agentkit", Path(tmp) / "code"
            subprocess.run(["git", "init", "-q", str(installed)], check=True)
            for message in ("installed", "merged"):
                subprocess.run(["git", "-C", str(installed), "-c", "user.name=acme", "-c",
                                "user.email=acme@example.com", "commit", "-q", "--allow-empty",
                                "-m", message], check=True)
            merged = gitcall.git(installed, "rev-parse", "HEAD")
            subprocess.run(["git", "clone", "-q", str(installed), str(source)], check=True)
            gitcall.git(installed, "checkout", "-q", "--detach", "HEAD~1")
            self.assertFalse(watch.health_command(source, merged, command)[0],
                             "a merge this host has not installed reads live from a source checkout")
            gitcall.git(installed, "checkout", "-q", "--detach", merged)
            pending = config.STATE / "agentkit-install-pending"
            pending.parent.mkdir(parents=True)
            pending.touch()
            self.assertFalse(watch.health_command(source, merged, command)[0],
                             "a merge whose install.sh has not passed reads live")
            pending.unlink()
            passed, output = watch.health_command(source, merged, command)
            self.assertTrue(passed, output)


if __name__ == "__main__":
    unittest.main()
