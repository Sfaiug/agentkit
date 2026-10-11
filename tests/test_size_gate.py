"""Past the size ceilings, ak refuses with `split it`.

A task has at most three checks a round runs (`task.MAX_CHECKS`, counted by preflight on the
list the loop settles: the repository's suite line, however the task names it, runs once at
landing and never counts; a `# once` line counts where the run has no landing), and a seat's own pull request
gets its first review only up to 400 added lines (`task.MAX_PR_LINES`), generated files aside
and nothing deleted counted, as `run.diff_lines` counts them, less the blocks `run.carried_lines`
finds moved unchanged from lines the diff deletes, as git marks them.  tests/test_own_pr_rounds.py drives the
refusal through the review itself.  Offline: a real checkout whose attributes mark a
generated file.
"""

import os
import re
import subprocess
import sys
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, record, run, task as taskfile


class SizeGate(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.repo / ".gitattributes").write_text("dist/*.js linguist-generated\n")
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
        refused = ("4 done-when checks: a task has at most 3, one behaviour a reviewer holds "
                   "in one read; split it")
        (self.repo / "AGENTS.md").write_text("---\ntests: python3 tests/suite.py 2>&1 | tee suite.log\n---\n# widget\n")
        three, suite = ["true", "true", "true"], "python3 tests/suite.py"
        checks = lambda cmds, **how: taskfile.group_commands(run.round_commands(
            cmds, self.repo, "main", scratch=False, **how))[0]
        # the list a round runs: the suite line, bare or whole, runs once at landing and never counts
        self.assertEqual(checks(three + [suite], landing=True), three)
        self.assertEqual(checks(three + ["bash tests/smoke.sh  # once"], landing=True), three)
        self.assertIsNone(taskfile.checks_refusal(checks(three + [suite], landing=True)))
        self.assertEqual(taskfile.checks_refusal(checks(three + ["false"], landing=True)), refused)
        # without a landing every line runs each round, `# once` or the suite's
        self.assertEqual(taskfile.checks_refusal(checks(three + [suite], landing=False)), refused)
        # the target's `tests:` line wins over the checkout's, as the loop reads it
        self.git("add", "AGENTS.md")
        self.git("commit", "-qm", "Declare the suite")
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        (self.repo / "AGENTS.md").write_text("---\n---\n# widget, behind origin\n")
        self.assertEqual(checks(three + [suite], landing=True), three)
        self.assertIsNone(taskfile.launch_refusal({}, ["true"] * 4))         # the ceiling is preflight's
        # ... which preflight applies: here a scratch task's `# once` line
        directory = config.RUNS / "20260102-0900-scratch"
        directory.mkdir(parents=True)
        (directory / "task.md").write_text("---\nrepo: none\n---\n# Scratch\n\n## Goal\nx\n\n## Done when\n"
                                           "```bash\ntrue\ntrue\ntrue\nbash tests/smoke.sh  # once\n```\n")
        record.save_state(directory, {"run_id": directory.name, "state": "queued"})
        with self.assertRaisesRegex(config.Error, "^" + re.escape(refused) + "$"):
            run.preflight(directory, {"--review-pr": None, "--no-merge": False}, lambda _: None)

    def test_the_lines_a_first_review_reads_leave_out_generated_files_and_deletions(self):
        self.assertEqual(run.diff_lines(self.repo, self.base, self.head, added_only=True), 2)
        self.assertEqual(run.diff_lines(self.repo, self.base, self.head), 8)     # the recorded size: old.py's four too
        # a change that only deletes adds nothing: a first review takes it whatever its size
        self.write({"api.py": "a\n"}, "Delete two lines")
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(run.diff_lines(self.repo, self.base, head, added_only=True), 0)
        self.assertEqual(run.diff_lines(self.repo, self.base, head), 6)
        self.assertIsNone(run.pr_size_refusal(7, taskfile.MAX_PR_LINES))
        self.assertEqual(run.pr_size_refusal(7, taskfile.MAX_PR_LINES + 1),
                         "PR #7 adds 401 lines (generated files aside; deletions never count): "
                         "a first review takes at most 400; split it")

    def test_lines_moved_unchanged_from_what_the_diff_deletes_never_count(self):
        self.git("checkout", "-q", self.base)
        self.git("checkout", "-qb", "split-big")
        # lines Git prints as `--- ` and `+++ ` inside a hunk are text, not a file's header
        body = (["-- schema", "++ counter"] + [f"line {n} = {n}" for n in range(498)]
                + ["", "", "tail = True"])
        # a submodule holds the module too, and the split re-indents its copy
        lib = ("-C", "lib", "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost")
        self.git("init", "-q", "lib")
        (self.repo / "lib/big.py").write_text("\n".join(body) + "\n")
        self.git(*lib, "add", "-A")
        self.git(*lib, "commit", "-qm", "Lib")
        self.write({"big.py": "\n".join(body) + "\n"}, "A big module")
        base = self.git("rev-parse", "HEAD")
        (self.repo / "big.py").unlink()
        (self.repo / "old.py").unlink()
        (self.repo / "parts").mkdir()
        (self.repo / "lib/big.py").write_text("".join(f"    {line}\n" for line in body))
        self.git(*lib, "commit", "-qam", "Re-indent")
        # one half moves as it was, the other re-indented into a class; two lines are new, and
        # a line the base had once is added twice; a generated file, its name holding a space,
        # takes old.py's lines
        self.write({"parts/a.py": "import os\n" + "\n".join(body[:250]) + "\n",
                    "parts/b.py": "class Half:\n" + "\n".join("    " + line for line in body[250:])
                    + "\ntail = True\n",
                    "dist/app bundle.js": "1\n2\n3\n4\n" + "tail = True\n" * 3}, "Split it")
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(run.carried_lines(self.repo, base, head), 503)
        added = run.diff_lines(self.repo, base, head, added_only=True)
        self.assertEqual(added, 507)     # the submodule's bump is one line
        # the user's own diff settings change nothing
        (self.repo / ".git/info/attributes").write_text("* diff=blank\n")
        for key, value in (("diff.noprefix", "true"), ("diff.external", "true"),
                           ("diff.blank.textconv", "true"), ("diff.submodule", "diff")):
            self.git("config", key, value)
        self.assertEqual(run.carried_lines(self.repo, base, head), 503)
        self.assertIsNone(run.pr_size_refusal(7, added, 503))
        self.assertEqual(run.pr_size_refusal(7, 1000, 599),
                         "PR #7 adds 1000 lines, 599 of them moved unchanged from lines it deletes "
                         "(generated files aside; deletions never count): a first review takes at "
                         "most 400; split it")
        self.assertIsNone(run.pr_size_refusal(7, 1000, 600))

    def test_a_module_replaced_by_fresh_code_moves_nothing(self):
        # the braces and blank lines the new code shares with the old are no moved block, and a
        # vendored tree deleted whole pairs with nothing in one pass
        self.git("checkout", "-q", self.base)
        self.git("checkout", "-qb", "replace")
        (self.repo / "vendor").mkdir()
        self.write({"old.js": "".join(f"function old_{n}() {{\n  return {n};\n}}\n\n" for n in range(300)),
                    **{f"vendor/f{f}.py": "".join(f"v_{f}_{n} = {n}\n" for n in range(100)) for f in range(40)}},
                   "An old module and a vendored tree")
        base = self.git("rev-parse", "HEAD")
        (self.repo / "old.js").unlink()
        self.git("rm", "-rq", "vendor")
        self.write({"new.js": "".join(f"function fresh_{n}(x) {{\n  return x * {n};\n}}\n\n" for n in range(130))},
                   "Fresh code in its place")
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(run.carried_lines(self.repo, base, head), 0)
        self.assertEqual(run.diff_lines(self.repo, base, head, added_only=True), 520)
        # the walk grows with the diff's size, never with its boilerplate squared: no step of
        # carried_lines per copy of a brace times its deleted copies
        steps, code = [0], run.carried_lines.__code__
        tracer = lambda frame, event, arg: (steps.__setitem__(0, steps[0] + 1), tracer)[1]
        sys.settrace(lambda frame, event, arg: tracer if frame.f_code is code else None)
        try:
            self.assertEqual(run.carried_lines(self.repo, base, head), 0)
        finally:
            sys.settrace(None)
        self.assertLessEqual(steps[0], 20 * (4000 + 300 * 4 + 520))
        # a short block that reads as moved is still new: fewer than twenty letters or digits
        self.write({"new.js": "function old_1() {\n  return 1;\n}\n"}, "A short block that was in old.js")
        self.assertEqual(run.carried_lines(self.repo, base, self.git("rev-parse", "HEAD")), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
