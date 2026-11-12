"""A git that asks no remote gets time by the host's load: one waiting for a core is not hung."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import gitcall


class LocalGitGetsTimeByLoad(unittest.TestCase):
    def code(self, verb, load):
        """tool_run's exit code for a git taking 3 s, TOOL_CAP being 1 s, at `load` per core."""
        busy = patch.object(os, "getloadavg", return_value=(load * (os.cpu_count() or 1), 0, 0))
        with tempfile.TemporaryDirectory() as shim, patch.object(gitcall, "TOOL_CAP", 1), busy:
            Path(shim, "git").write_text("#!/bin/sh\nsleep 3\n")
            Path(shim, "git").chmod(0o755)
            return gitcall.tool_run(["git", verb], env={"PATH": f"{shim}:{os.environ['PATH']}"})[0]

    def test_only_a_git_asking_no_remote_is_waited_for_and_only_on_a_busy_host(self):
        self.assertEqual(self.code("status", 600), 0)
        self.assertIsNone(self.code("status", 0.5))     # a core is free: killed at the cap
        self.assertIsNone(self.code("fetch", 600))      # it asks a remote: the cap, however busy

    def test_no_load_buys_more_than_the_ceiling(self):
        with patch.object(os, "getloadavg", return_value=(1e9, 0, 0)):
            self.assertEqual(gitcall.local_cap(), gitcall.LOCAL_CEILING)


if __name__ == "__main__":
    unittest.main()
