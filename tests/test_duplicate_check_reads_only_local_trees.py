"""Duplicate detection reads local paths without fetching missing blobs or trees."""

import os
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import run
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class LocalTreesOnly(unittest.TestCase):
    def test_partial_clones_never_fetch_during_duplicate_detection(self):
        with Home() as home, patch.dict(os.environ, home.env, clear=True):
            rig = Rig(home, "widgets", files={"tests/test_guard.py": "pass\n"})
            rig.origin("config", "uploadpack.allowFilter", "true")

            def git(where, *args):
                done = home.run("git", "-C", str(where), *args, timeout=20)
                self.assertEqual(done.code, 0, done.out + done.err)
                return done.out.strip()

            for filter_, expected in (("blob:none", ["tests/test_new.py"]),
                                      ("tree:0", ["./tests/test_guard.py", "tests/test_new.py"])):
                with self.subTest(filter=filter_):
                    clone = home.path / filter_.replace(":", "-")
                    git(home.path, "clone", "-q", f"--filter={filter_}", "--no-checkout",
                        rig.bare.as_uri(), str(clone))
                    marker = clone / "fetch-attempted"
                    hook = clone / "upload-pack"
                    hook.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 1\n")
                    hook.chmod(0o755)
                    git(clone, "config", "remote.origin.uploadpack", str(hook))
                    held = clone / "held"
                    held.mkdir()
                    commands = ["python3 './tests/test_guard.py'", "python3 tests/test_new.py"]
                    (held / "task.md").write_text(
                        "# Improve upload progress\n\n## Done when\n```bash\n"
                        + "\n".join(commands) + "\n```\n")
                    state = {"state": "running", "repo": str(clone)}
                    with patch.object(run.run_record, "run_dirs", return_value=[]) as dirs, \
                            patch.object(run.run_record, "read_state", return_value=state), \
                            patch.object(run.run_record, "process_active", return_value=True):
                        for active in ([], [held]):
                            dirs.return_value = active
                            matches = run.already_under_way(
                                clone / "task.md", {"repo": str(clone)},
                                "Improve upload labels", commands)
                            self.assertFalse(marker.exists(), "duplicate detection attempted a fetch")
                            self.assertEqual([match["files"] for match in matches],
                                             [expected] if active else [])


if __name__ == "__main__":
    unittest.main()
