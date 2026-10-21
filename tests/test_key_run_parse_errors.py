"""`ak run` refuses a command line it cannot act on with exit 2 and one line saying why, and
starts nothing; `ak run --help` lists each verb of `ak run` and no hidden one.

A model learns `ak run` by trying it: a typo, a missing id or a round count over the budget must
cost it one plain line on stderr, never a run directory, a tmux session or a call to GitHub or a
harness, and the line must say what to type instead.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSED, Home

BUDGET = ("is over the budget: 3 rounds, then a run goes back to its orchestrator to split or"
          " re-scope")
# Each refused command line after `ak run`, and the line ak prints for it after `ak run: `;
# `…` stands for text this test does not pin, such as the rest of a usage block.
BAD_LINES = {
    (): "usage: ak run <task.md> …",
    ("--exec",): "--exec needs a value",
    ("t.md", "--rounds", "0"): "--rounds must be a positive integer (got '0')",
    ("t.md", "--rounds", "4"): f"--rounds 4 {BUDGET}",
    ("t.md", "--rounds", "5"): f"--rounds 5 {BUDGET}",
    ("--review-pr",): "--review-pr needs a value",
    ("--review-pr", "bad"): "--review-pr needs a GitHub PR URL (got 'bad')",
    ("t.md", "--x"): "unknown flag '--x'; ak run <task.md> …",
    ("t.md", "--parallel", "2"): "…--parallel needs more than one task file",
    ("status", "--bogus"): "usage: ak run status …",
    ("gc", "--bogus"): "usage: ak run gc [--dry-run]",
    ("stop",): "usage: ak run stop ID [--keep]",
    ("resume",): "usage: ak run resume …",
    ("merge",): "usage: ak run merge …",
    ("clean",): "usage: ak run clean …",
    ("--lander", "x"): "usage: ak run --lander LINE",
}
LOOKUPS = {
    "status": "no such run: nope (looked in {runs})",
    "stop": "no such run: nope (looked in {runs})",
    "clean": "no such run: nope (looked in {runs})",
    "resume": "no resumable run: nope (looked in {runs})",
    "merge": "nope: merge requires a finished PASS",
}
VERBS = ["TASK", "--review-pr", "status", "resume", "stop", "merge", "clean", "gc"]
USAGES = ("usage: ak run TASK", "ak run --review-pr URL", "ak run status [ID]", "ak run resume ID",
          "ak run stop ID [--keep]", "ak run merge ID", "ak run clean ID", "ak run gc [--dry-run]")


def files(home):
    return {path: path.read_bytes() for path in home.path.rglob("*") if path.is_file()}


class RunCommandLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write("t.md", "# fix-api\n\nReturn 404 for a missing user.\n")

    def refused(self, args, said, home=None, cwd=None):
        """Run `ak run ARGS` and hold that it printed only `ak run: SAID` and started nothing."""
        home = home or self.home
        before = files(home)
        done = home.ak("run", *args, cwd=cwd)
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        pattern = ".*".join(map(re.escape, f"ak run: {said}\n".split("…")))
        self.assertTrue(re.fullmatch(pattern, done.err), done.err)
        self.assertEqual(files(home), before)
        runs = home.path / ".agentkit" / "runs"
        self.assertEqual(list(runs.iterdir()) if runs.is_dir() else [], [])
        self.assertNotEqual(home.tmux("list-sessions").code, 0, "a tmux session started")
        self.assertEqual([tool for tool in REFUSED if home.calls(tool)], [])

    def test_a_bad_command_line_exits_2_with_one_line_saying_why_and_starts_nothing(self):
        for args, said in BAD_LINES.items():
            with self.subTest(args=args):
                self.refused(args, said)

    def test_a_task_file_that_is_not_there_is_named_by_its_full_path(self):
        cwd = self.home.path / "code" / "acme"
        cwd.mkdir(parents=True, exist_ok=True)
        self.refused(("missing.md",), f"no such task file: {cwd}/missing.md", cwd=cwd)
        absent = self.home.root / "tmp" / "missing.md"
        self.refused((str(absent),), f"no such task file: {absent}")

    def test_an_unknown_run_id_exits_2_and_says_where_ak_looked(self):
        runs = self.home.path / ".agentkit" / "runs"
        for verb, said in LOOKUPS.items():
            with self.subTest(verb):
                self.refused((verb, "nope"), said.format(runs=runs))

    def test_a_run_id_that_is_a_path_reaches_nothing_outside_the_runs(self):
        with Home() as home:
            # a record every verb would act on, were it inside the runs
            home.write(".agentkit/acme/run.json", {"state": "pass", "verdict": "PASS",
                                                   "repo": str(home.path),
                                                   "worktree": str(home.path)})
            (home.path / ".agentkit" / "runs").mkdir()
            for verb in LOOKUPS:
                with self.subTest(verb):
                    said = (f"no such run: ../acme (looked in {home.path}/.agentkit/runs)"
                            if verb == "status" else f"usage: ak run {verb} …")
                    self.refused((verb, "../acme"), said, home=home)

    def test_run_help_lists_each_verb_of_ak_run_in_its_usage_block(self):
        done = self.home.ak("run", "--help")
        self.assertEqual(done.code, 0, done.err)
        usage = done.out.split("usage: ", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(re.findall(r"ak run (\S+)", usage), VERBS)
        for shown in USAGES:
            self.assertIn(shown, done.out)

    def test_run_help_never_mentions_the_hidden_pending_flag_or_the_show_alias(self):
        done = self.home.ak("run", "--help")
        self.assertEqual(done.code, 0, done.err)
        self.assertNotIn("--pending", done.out)
        self.assertNotIn("ak run show", done.out)


if __name__ == "__main__":
    unittest.main()
