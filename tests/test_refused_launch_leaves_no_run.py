"""A launch refused for its config leaves no run behind; one that is accepted still starts.

Offline: the bin/ak entry point with a temporary HOME; preflight, scope and the loop are mocked.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run

AK_MAIN = runpy.run_path(str(REPO / "bin/ak"))["main"]


class RefusedLaunchLeavesNoRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-refused-launch-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "JOBS"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": ""}))
        stack.enter_context(patch.object(config, "current_session", return_value=None))
        stack.enter_context(patch.object(run, "preflight"))
        stack.enter_context(patch.object(
            orch, "scope_self", side_effect=lambda _unit, _slice, _props, placement: placement.update(
                scope="none", scope_reason="no user manager in a test") or False))
        self.drive = stack.enter_context(patch.object(run, "drive", return_value=0))
        home.mkdir()
        self.task = self.root / "fix-api.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the api\n\n## Done when\n```bash\ntrue\n```\n")

    def runs(self):
        # a run is its directory; the runs folder also holds locks
        return [path for path in config.RUNS.glob("*") if path.is_dir()]

    def launch(self, setting):
        (config.HOME / "config.toml").write_text(f"run_memory_max_mb = {setting}\n")
        err = io.StringIO()
        with patch.object(sys, "argv", [str(REPO / "bin/ak"), "run", str(self.task), "--no-merge"]), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            return AK_MAIN(), err.getvalue()

    def test_an_invalid_memory_cap_refuses_before_any_run_exists(self):
        for setting in ("0", "-5", '"512"', "true"):
            with self.subTest(setting=setting):
                code, err = self.launch(setting)
                self.assertEqual(code, 2, err)
                self.assertIn("run_memory_max_mb must be a positive integer", err)
                self.assertEqual(self.runs(), [])
                self.drive.assert_not_called()

    def test_a_valid_memory_cap_still_launches(self):
        code, err = self.launch("512")
        self.assertEqual(code, 0, err)
        self.assertEqual([path.name.endswith("-fix-the-api") for path in self.runs()], [True])
        self.drive.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
