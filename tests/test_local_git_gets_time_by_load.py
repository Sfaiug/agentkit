"""A git that asks no remote gets time by the host's load: one waiting for a core is not hung."""
from contextlib import contextmanager
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import gitcall, roundloop

# Answers after 2 s: a `merge-file` with one conflict over an empty base, any other with a word.
GIT = """#!/bin/sh
sleep 2
case "$*" in *merge-file*) printf '||||||| base\\n=======\\n'; exit 1 ;; esac
echo said
"""


class LocalGitGetsTimeByLoad(unittest.TestCase):
    @contextmanager
    def host(self, load):
        """A host at `load` per core whose git takes 2 s to answer, TOOL_CAP being 1 s."""
        busy = patch.object(os, "getloadavg", return_value=(load * (os.cpu_count() or 1), 0, 0))
        with tempfile.TemporaryDirectory() as shim, patch.object(gitcall, "TOOL_CAP", 1), busy, \
                patch.dict(os.environ, {"PATH": f"{shim}:{os.environ['PATH']}"}):
            Path(shim, "git").write_text(GIT)
            Path(shim, "git").chmod(0o755)
            yield

    def code(self, verb, load):
        """tool_run's exit code for that git on that host."""
        with self.host(load):
            return gitcall.tool_run(["git", verb])[0]

    def test_only_a_git_asking_no_remote_is_waited_for_and_only_on_a_busy_host(self):
        self.assertEqual(self.code("status", 600), 0)
        self.assertIsNone(self.code("status", 0.5))     # a core is free: killed at the cap
        self.assertIsNone(self.code("fetch", 600))      # it asks a remote: the cap, however busy

    def test_a_git_started_outside_tool_run_is_waited_for_alike(self):
        with self.host(600):
            self.assertEqual(gitcall.git_bytes(".", "status"), "said\n")
            self.assertEqual(gitcall.rules_bytes(".", "HEAD"), b"said\n")
            self.assertEqual(roundloop.patch_id(".", "HEAD"), "said")
            self.assertEqual(roundloop.conflict_added_only(".", "AGENTS.md"), 1)

    def test_no_load_buys_more_than_the_ceiling(self):
        with patch.object(os, "getloadavg", return_value=(1e9, 0, 0)):
            self.assertEqual(gitcall.local_cap(), gitcall.LOCAL_CEILING)


if __name__ == "__main__":
    unittest.main()
