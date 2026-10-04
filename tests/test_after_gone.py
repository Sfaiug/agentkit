"""A task file naming `after:` is refused at launch, alone or in a job, before any receipt.

Offline: the bin/ak entry point with a temporary HOME and launch effects mocked out.
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
from agentkit import config, job, run, task

AK_MAIN = runpy.run_path(str(REPO / "bin/ak"))["main"]


class AfterGone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-after-gone-", dir=REPO)
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
        stack.enter_context(patch.object(config, "load", return_value={}))
        stack.enter_context(patch.object(config, "current_session", return_value=None))
        self.prepare = stack.enter_context(patch.object(run, "prepare"))
        self.drive = stack.enter_context(patch.object(run, "drive", return_value=0))
        self.job_loop = stack.enter_context(patch.object(job, "run_job_loop", return_value=0))

    def write(self, front, name):
        path = self.root / name
        path.write_text(f"---\nrepo: none\n{front}---\n# {name}\n\n## Done when\n```bash\ntrue\n```\n")
        return path

    def launch(self, *paths):
        err = io.StringIO()
        with patch.object(sys, "argv", [str(REPO / "bin/ak"), "run", *map(str, paths)]), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = AK_MAIN()
        return code, err.getvalue()

    def assert_nothing_started(self):
        self.assertFalse(config.RUNS.exists() and any(config.RUNS.iterdir()))
        self.assertFalse(config.JOBS.exists() and any(config.JOBS.iterdir()))
        self.prepare.assert_not_called()
        self.drive.assert_not_called()
        self.job_loop.assert_not_called()

    def test_a_single_task_with_after_is_refused(self):
        code, err = self.launch(self.write("after: base.md\n", "fix-api.md"))
        self.assertEqual(code, 2, err)
        self.assertIn("`after:` is gone", err)
        self.assert_nothing_started()

    def test_a_job_with_after_is_refused_before_its_receipt(self):
        first = self.write("", "base.md")
        second = self.write("after: base.md\n", "fix-api.md")
        code, err = self.launch(first, second, "--anyway")
        self.assertEqual(code, 2, err)
        self.assertIn(f"{second}: `after:` is gone", err)
        self.assert_nothing_started()

    def test_an_old_run_copy_with_after_still_parses(self):
        meta, _, title = task.parse_task(self.write("after: base.md\n", "fix-api.md"))
        self.assertEqual((meta["after"], title), ("base.md", "fix-api.md"))
        self.assertIn("`after:` is gone", task.launch_refusal(meta))


if __name__ == "__main__":
    unittest.main(verbosity=2)
