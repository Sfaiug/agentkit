"""agentkit's own `health:` passes only once the ak this host installed works: `ak doctor` exits 1
when no tick has ended within `TICK_HUNG` and fails outright on an install that cannot run.

Offline: a temporary HOME, a stand-in `bin/ak` and the tick's own probe.
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


class HealthNeedsAWorkingAk(unittest.TestCase):
    def setUp(self):
        self.command = gitcall.front_value((REPO / "AGENTS.md").read_text(), "health")
        self.assertTrue(self.command, "AGENTS.md declares no health:")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (patch.dict(os.environ, {"HOME": tmp.name}),
                        patch.object(config, "HOME", Path(tmp.name) / ".agentkit")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.home = Path(tmp.name)
        self.installed = self.home / "agentkit"
        subprocess.run(["git", "init", "-q", str(self.installed)], check=True)
        for message in ("installed", "merged"):
            subprocess.run(["git", "-C", str(self.installed), "-c", "user.name=acme", "-c",
                            "user.email=acme@example.com", "commit", "-q", "--allow-empty",
                            "-m", message], check=True)
        self.merged = gitcall.git(self.installed, "rev-parse", "HEAD")

    def ak_doctor_exits(self, code):
        """`bin/ak doctor` exits `code` and leaves a mark; anything else it is asked is a failure."""
        ak = self.installed / "bin" / "ak"
        ak.parent.mkdir(exist_ok=True)
        ak.write_text(f'#!/bin/sh\ntouch "$HOME/ran"\n[ "$1" = doctor ] || exit 2\nexit {code}\n')
        ak.chmod(0o755)

    def probe(self):
        return watch.health_command(self.home, self.merged, self.command)

    def test_an_ak_that_exits_1_fails_the_probe(self):
        self.ak_doctor_exits(1)
        self.assertFalse(self.probe()[0], "a merge whose installed ak is hung reads live")
        self.assertTrue((self.home / "ran").exists(), "the probe never ran the installed ak")

    def test_an_ak_that_exits_0_passes_the_probe(self):
        self.ak_doctor_exits(0)
        passed, output = self.probe()
        self.assertTrue(passed, output)
        self.assertTrue((self.home / "ran").exists(), "the probe never ran the installed ak")

    def test_a_merge_not_installed_fails_first(self):
        self.ak_doctor_exits(0)
        gitcall.git(self.installed, "checkout", "-q", "--detach", "HEAD~1")
        self.assertFalse(self.probe()[0], "a merge this host has not installed reads live")
        self.assertFalse((self.home / "ran").exists(), "ak ran before the merge was found installed")

    def test_an_install_pending_fails_first(self):
        self.ak_doctor_exits(0)
        pending = config.STATE / "agentkit-install-pending"
        pending.parent.mkdir(parents=True)
        pending.touch()
        self.assertFalse(self.probe()[0], "a merge whose install.sh has not passed reads live")
        self.assertFalse((self.home / "ran").exists(), "ak ran before the install passed")


if __name__ == "__main__":
    unittest.main()
