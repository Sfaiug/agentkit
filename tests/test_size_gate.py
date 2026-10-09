"""Past the size ceilings, ak refuses with `split it`.

A task has at most three per-round checks (`task.MAX_CHECKS`; a `# once` line is the suite's
where the run lands, a check of its own where it does not), and a seat's own pull request
gets its first review only up to 400 changed lines (`task.MAX_PR_LINES`), generated files and
pure deletions aside as `run.diff_lines` counts them.  tests/test_own_pr_rounds.py drives the
refusal through the review itself.  Offline: a real checkout whose attributes mark a
generated file.
"""

import os
import subprocess
import unittest

from fixtures.sandbox import Sandbox
from agentkit import run, task as taskfile


class SizeGate(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.repo / ".gitattributes").write_text("dist/* linguist-generated\n")
        (self.repo / "dist").mkdir()
        self.write({"api.py": "a\nb\nc\n", "dist/app.js": "built\n", "old.py": "1\n2\n3\n4\n"}, "Base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "fix-api")
        (self.repo / "old.py").unlink()
        self.write({"api.py": "a\nB\nC\n", "dist/app.js": "rebuilt\n" * 900}, "Change")
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()

    def write(self, files, message):
        for name, content in files.items():
            (self.repo / name).write_text(content)
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def test_a_task_has_at_most_three_per_round_checks(self):
        self.assertIsNone(taskfile.launch_refusal({}, ["true", "true", "true"]))
        self.assertIsNone(taskfile.launch_refusal({}, ["true", "true", "true", "bash tests/smoke.sh  # once"]))
        refused = ("4 done-when checks: a task has at most 3, one behaviour a reviewer holds "
                   "in one read; split it")
        self.assertEqual(taskfile.launch_refusal({}, ["true"] * 4), refused)
        # without a landing the `# once` line runs every round, and counts
        self.assertEqual(taskfile.launch_refusal({}, ["true", "true", "true", "bash tests/smoke.sh  # once"],
                                                 landing=False), refused)

    def test_the_lines_a_first_review_reads_leave_out_generated_files_and_deletions(self):
        self.assertEqual(run.diff_lines(self.repo, self.base, self.head, removed=False), 4)
        self.assertEqual(run.diff_lines(self.repo, self.base, self.head), 8)     # old.py's four
        self.assertIsNone(run.pr_size_refusal(7, taskfile.MAX_PR_LINES))
        self.assertEqual(run.pr_size_refusal(7, taskfile.MAX_PR_LINES + 1),
                         "PR #7 changes 401 lines (generated files and pure deletions aside): "
                         "a first review takes at most 400; split it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
