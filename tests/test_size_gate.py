"""Past the size ceilings, ak refuses with `split it`.

Owner rule, 3 Oct, 4 Oct, 9 Oct, 11 Oct, 13 Oct, 15 Oct, 16 Oct, 20 Oct 2026: "A change's first
review takes at most 400 added lines, a seat's own pull request's and a task's alike (deletions and
unchanged moves never count), and a task at most three checks a round runs: past either, ak refuses
with `split it`. Reason: 81% of 201-400-line changes merged, 67% of larger ones (1-16 Oct); it is
looked at again in early November on first-review sizes recorded since. Review rounds stay three,
and a pull request mostly re-adding a failed one's lines inherits its rounds. No cap on task points
or words: size is recorded and shown. Nothing ak hands a model is cut." Held here with
tests/test_own_pr_rounds.py, tests/test_replacement_pr_rounds.py, tests/test_task_size.py and
tests/test_rules_cap_told.py.

A task has at most three checks a round runs (`task.MAX_CHECKS`, counted by preflight on the
list the loop settles: the repository's suite line, however the task names it, runs once at
landing and never counts; a `# once` line counts where the run has no landing), and a change,
a seat's own pull request or a task's, gets its first review only up to 400 added lines
(`task.MAX_PR_LINES`), generated files aside
and nothing deleted counted, as `run.diff_lines` counts them, less the blocks `run.carried_lines`
finds moved unchanged from lines the diff deletes.  tests/test_own_pr_rounds.py drives the
refusal through the review itself.  Offline: a real checkout whose attributes mark a
generated file.
"""

import os
import re
import subprocess
import sys
import unittest

from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, record, roundloop, run, task as taskfile, transitions, turns


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

    def test_a_task_s_first_review_takes_at_most_400_added_lines(self):
        # the branch already adds 2 lines a reviewer reads (dist/ is generated); the executor
        # adds the rest, uncommitted, as executors do
        def loop(run_id, change=None, **extra):
            state = {"run_id": run_id, "title": "Fix the API", "state": "running", "repo": str(self.repo),
                     "worktree": str(self.repo), "base": "main", "base_sha": self.base,
                     "branch": "fix-api", "executor": "opus", "reviewer": "astra", "rounds": 3,
                     "round_summaries": [], **({"change": change} if change else {}), **extra}
            directory = config.RUNS / run_id
            directory.mkdir(parents=True)
            record.save_state(directory, state)
            history.start_run(run_id, repo=str(self.repo))
            return run.Loop(config.load(), directory, state, {}, lambda _s: None, self.repo,
                            "# Fix the API", ["true"], "Do the task.")

        read = []

        def judged(lp):
            # what the first review reads is in the run's history row before any verdict, so a
            # run that ends FAIL, blocked or stopped keeps it as a pass does
            read.append(history.get(lp.state["run_id"])["first_review_lines"])
            return "PASS"

        def rounds(lp, lines):
            def build(*_args):
                (self.repo / "new.py").write_text("".join(f"n{k} = {k}\n" for k in range(lines)))
                return "built"
            with patch.object(roundloop, "execute", side_effect=build), \
                    patch.object(run, "pickup_new_code", return_value=None), \
                    patch.object(roundloop, "verify_work", return_value=(True, "$ true\n[exit 0]")), \
                    patch.object(roundloop, "review", side_effect=lambda *_a, **_k: judged(lp)) as review:
                try:
                    run.rounds(lp)
                except turns.Blocked as blocked:
                    return review.call_count, str(blocked), blocked.section
            return review.call_count, None, None

        self.assertEqual(rounds(loop("20261015-0900-at-the-ceiling"), taskfile.MAX_PR_LINES - 2),
                         (1, None, None))
        self.git("reset", "-q", "--hard", self.head)
        reviewed, why, section = rounds(loop("20261015-0910-past-it"), taskfile.MAX_PR_LINES - 1)
        refused = ("The change on fix-api adds 401 lines (generated files aside; deletions never "
                   "count): a first review takes at most 400; split it")
        self.assertEqual((reviewed, why, section), (0, refused, f"## Blocked\n\n{refused}"))
        self.assertIsNone(history.get("20261015-0910-past-it")["first_review_lines"])
        # the work is committed on the branch the blocked run keeps, for the pieces
        self.assertIn("new.py", self.git("show", "--name-only", "--format=", "HEAD"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        # a round another run of the change has under way, its reviewer yet to judge, is no review
        self.git("reset", "-q", "--hard", self.head)
        earlier = config.RUNS / "20261015-0800-first-try"
        earlier.mkdir(parents=True)
        record.save_state(earlier, {"run_id": earlier.name, "state": "running", "change": "the-change",
                                    "step_round": 1, "round_summaries": []})
        self.assertEqual(rounds(loop("20261015-0915-beside-it", "the-change"), taskfile.MAX_PR_LINES - 1)[:2],
                         (0, refused))
        # ... nor is a first review resumed on the saved work
        self.git("reset", "-q", "--hard", self.head)
        (self.repo / "new.py").write_text("".join(f"n{k} = {k}\n" for k in range(taskfile.MAX_PR_LINES - 1)))
        self.assertEqual(rounds(loop("20261015-0918-resumed", review_pending={"round": 1, "summary": "built"}),
                                0)[:2], (0, refused))
        # a change a run launched `from:` its branch already had reviewed is past its first review
        self.git("reset", "-q", "--hard", self.head)
        record.save_state(earlier, {"run_id": earlier.name, "state": "fail", "change": "the-change",
                                    "round_summaries": [{"round": 1, "verdict": "FAIL"}]})
        self.assertEqual(rounds(loop("20261015-0920-from-its-branch", "the-change"),
                                taskfile.MAX_PR_LINES), (1, None, None))
        # the first review read 400 lines; a later review of the change is no first review
        self.assertEqual(read, [taskfile.MAX_PR_LINES, None])

    def test_a_first_review_resumed_before_its_verdict_keeps_the_size_it_first_read(self):
        self.enterContext(patch.dict(os.environ, {"AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
                                                  "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
                                                  "AK_MAX_RUNS": "0"}))
        directory = config.RUNS / "20261015-0930-interrupted"
        directory.mkdir(parents=True)
        state = {"run_id": directory.name, "title": "Fix the API", "state": "running",
                 "repo": str(self.repo), "worktree": str(self.repo), "base": "main",
                 "base_sha": self.base, "branch": "fix-api", "executor": "opus",
                 "reviewer": "astra", "rounds": 3, "round_summaries": []}
        record.save_state(directory, state)
        history.start_run(directory.name, repo=str(self.repo))
        lp = run.Loop(config.load(), directory, state, {}, lambda _s: None, self.repo,
                      "# Fix the API", ["true"], "Do the task.")

        def interrupted(lp, summary, *_a, **_k):
            lp.state["review_pending"] = {"round": lp.rnd, "summary": summary}
            lp.save()
            raise turns.Exhausted("stopped before a verdict")

        with patch.object(roundloop, "execute", return_value="built"), \
                patch.object(run, "pickup_new_code", return_value=None), \
                patch.object(roundloop, "verify_work", return_value=(True, "$ true\n[exit 0]")):
            with patch.object(roundloop, "review", side_effect=interrupted), \
                    self.assertRaises(turns.Exhausted):
                run.rounds(lp)
            # the work grows while the review waits
            self.write({"extra.py": "extra = 1\n"}, "More work")
            with patch.object(roundloop, "review", return_value="PASS"):
                roundloop.resume_review(lp)
        self.assertEqual(history.get(directory.name)["first_review_lines"], 2)

    def test_the_lines_a_first_review_reads_leave_out_generated_files_and_deletions(self):
        self.assertEqual(run.diff_lines(self.repo, self.base, self.head, added_only=True), 2)
        self.assertEqual(run.diff_lines(self.repo, self.base, self.head), 8)     # the recorded size: old.py's four too
        # a change that only deletes adds nothing: a first review takes it whatever its size
        self.write({"api.py": "a\n"}, "Delete two lines")
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(run.diff_lines(self.repo, self.base, head, added_only=True), 0)
        self.assertEqual(run.diff_lines(self.repo, self.base, head), 6)
        self.assertIsNone(run.first_review_refusal("PR #7", taskfile.MAX_PR_LINES))
        self.assertEqual(run.first_review_refusal("PR #7", taskfile.MAX_PR_LINES + 1),
                         "PR #7 adds 401 lines (generated files aside; deletions never count): "
                         "a first review takes at most 400; split it")

    def test_a_change_cannot_mark_its_own_lines_generated(self):
        # the base marks dist/*.js generated; a change marking its own new file generated in
        # the same diff still has every line of it counted, beside the attribute line (ATLAS
        # #2453 on 16 Oct 2026: 2,943 lines read as 241)
        self.git("checkout", "-q", self.base)
        self.git("checkout", "-qb", "self-marked")
        self.write({".gitattributes": "dist/*.js linguist-generated\nfixtures/* linguist-generated\n",
                    "dist/bundle.js": "built\n" * 50}, "Mark the fixtures generated")
        (self.repo / "fixtures").mkdir()
        self.write({"fixtures/recorded.json": "{}\n" * 500}, "Record the fixtures")
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(run.diff_lines(self.repo, self.base, head, added_only=True), 501)
        self.assertEqual(transitions.reviewed_lines(self.repo, self.base, head)[0].total(), 501)
        self.assertIn("split it", run.first_review_refusal("PR #7", 501))
        # ... and once the marking has landed on its own, the fixtures are generated
        self.assertEqual(run.diff_lines(self.repo, self.git("rev-parse", "HEAD~1"), head,
                                        added_only=True), 0)

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
        self.assertIsNone(run.first_review_refusal("PR #7", added, 503))
        self.assertEqual(run.first_review_refusal("PR #7", 1000, 599),
                         "PR #7 adds 1000 lines, 599 of them moved unchanged from lines it deletes "
                         "(generated files aside; deletions never count): a first review takes at "
                         "most 400; split it")
        self.assertIsNone(run.first_review_refusal("PR #7", 1000, 600))

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
        self.assertEqual(run.diff_lines(self.repo, base, head, added_only=True), 520)
        # the walk grows with the diff's size, never with its boilerplate squared: no step of
        # carried_lines or its windows per copy of a brace times its deleted copies
        carried, steps = self.traced(self.repo, base, head)
        self.assertEqual(carried, 0)
        self.assertLessEqual(steps, 20 * (4000 + 300 * 4 + 520))
        # a short block that reads as moved is still new: fewer than MOVED_BLOCK letters or digits
        self.write({"new.js": "function old_1() {\n  return 1;\n}\n"}, "A short block that was in old.js")
        self.assertEqual(run.carried_lines(self.repo, base, self.git("rev-parse", "HEAD")), 0)

    def traced(self, *args):
        """`run.carried_lines(*args)` and the Python steps its walk and windows took."""
        steps, codes = [0], (transitions.reviewed_lines.__code__, transitions._windows.__code__)
        tracer = lambda frame, event, arg: (steps.__setitem__(0, steps[0] + 1), tracer)[1]
        sys.settrace(lambda frame, event, arg: tracer if frame.f_code in codes else None)
        try:
            return run.carried_lines(*args), steps[0]
        finally:
            sys.settrace(None)

    def test_punctuation_runs_and_repeated_headers_cost_the_diffs_size(self):
        # a punctuation-only line starts no window, however long its run, so a maze split into
        # levels is walked once, not once per row; a header every file opens on pairs each of
        # its deleted copies with one added copy, in order, so copies never multiply
        self.assertEqual(transitions._windows(["#" * 40] * 3 + ["the exit of the maze is on the last row"]),
                         [None, None, None, ("the exit of the maze is on the last row",)])
        self.git("checkout", "-q", self.base)
        self.git("checkout", "-qb", "runs")
        row = "#" + "." * 38 + "#\n"
        header = ("// Copyright 2026 The Acme Authors. All rights reserved.\n"
                  "// Use of this source code is governed by a BSD-style\n"
                  "// license that can be found in the LICENSE file.\n\n")
        (self.repo / "lib1").mkdir()
        self.write({"maze.txt": row * 3000 + "the exit of the maze is on the last row\n",
                    **{f"lib1/m{n}.go": header + f"package lib1\n\nfunc A{n}() int {{ return {n} }}\n"
                       + "".join(f"var a{n}_{k} = {k}\n" for k in range(6))
                       for n in range(300)}}, "A maze and a library")
        base = self.git("rev-parse", "HEAD")
        (self.repo / "maze.txt").unlink()
        self.git("rm", "-rq", "lib1")
        (self.repo / "lib2").mkdir()
        self.write({**{f"level{n}.txt": row * 1000 + f"the exit of level {n} is on the last row\n"
                       for n in range(3)},
                    **{f"lib2/n{n}.go": header + f"package lib2\n\nfunc B{n}() int {{ return {n} * 7 }}\n"
                       + "".join(f"var b{n}_{k} = {k} * 7\n" for k in range(6))
                       for n in range(300)}}, "Three levels and the next library")
        head = self.git("rev-parse", "HEAD")
        carried, steps = self.traced(self.repo, base, head)
        # each deleted header carries one added header; a file git pairs as a rename shows no
        # header in the diff at all, so the count is the whole adds' under lib2
        whole = self.git("diff", "--name-only", "--find-renames", "--diff-filter=A", f"{base}..{head}")
        self.assertEqual(carried, 4 * sum(name.startswith("lib2/") for name in whole.splitlines()))
        self.assertLessEqual(steps, 20 * (3001 + 3003 + 2 * 300 * 13))

if __name__ == "__main__":
    unittest.main(verbosity=2)
