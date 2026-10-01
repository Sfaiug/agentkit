"""Unknown task keys refuse launch before receipts; all existing keys still parse.

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
KEYS = ("after", "base", "done_when_minutes", "files", "from", "merge", "repo",
        "rounds", "stall_minutes", "target", "turn_hours")


class UnknownFrontMatterKey(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-unknown-key-", dir=REPO)
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

    def write(self, front, name="fix-api.md"):
        path = self.root / name
        path.write_text(f"---\n{front}---\n# Fix the api\n\n## Done when\n```bash\ntrue\n```\n")
        return path

    def refuse(self, *args, path, key):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", [str(REPO / "bin/ak"), "run", *map(str, args)]), \
                redirect_stdout(out), redirect_stderr(err):
            code = AK_MAIN()
        self.assertEqual(code, 2, err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), f"ak run: {path}: unknown front-matter key {key!r}; "
                         f"accepted keys: {', '.join(KEYS)}\n")
        self.assertEqual(list(config.RUNS.iterdir()), [])
        self.assertEqual(list(config.JOBS.iterdir()), [])
        self.prepare.assert_not_called()
        self.drive.assert_not_called()
        self.job_loop.assert_not_called()

    def test_unknown_keys_refuse_single_launch_even_with_anyway(self):
        for key, value in (("form", "ak/fix-api"), ("afer", "base.md"), ("future", "")):
            with self.subTest(key=key):
                path = self.write(f"repo: none\n  {key} : {value} # comment\n")
                self.refuse(path, "--anyway", path=path, key=key)

    def test_unknown_key_refuses_a_job_before_any_receipt(self):
        first = self.write("repo: none\n", "base.md")
        second = self.write("repo: none\nafer: base.md\n")
        self.refuse(first, second, path=second, key="afer")

    def test_all_existing_keys_and_repeated_lines_still_parse(self):
        path = self.write("".join(f"{key}: value\n" for key in KEYS)
                          + "after: base.md, schema.md\nfiles: src/, tests/\nfiles: docs/\n")
        meta, _, title = task.parse_task(path)
        self.assertEqual(set(meta), set(KEYS))
        self.assertEqual(title, "Fix the api")
        self.assertEqual(task.task_afters(path), ["value", "base.md", "schema.md"])
        self.assertEqual(task.task_files(path), ["value", "src/", "tests/", "docs/"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
