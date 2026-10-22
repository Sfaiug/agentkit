"""A task ak cannot run as written is refused with exit 2 and one sentence saying what to change.

Orchestrators learn the task rules from these refusals, so each says plainly what is wrong: a
`## Done when` with no checks in a bash block, a check line that opens a heredoc (each line
runs as a command of its own), more than 3 rounds asked for in the front matter or with
`--rounds`, and more than 3 checks a round runs (`split it`: one behaviour a reviewer holds in
one read).  The first three are refused before anything exists, in the foreground and with
`--bg` alike: no run directory, job, branch or worktree, and no harness called.  The checks
ceiling is settled in preflight, against the list a round runs, where a `# once` line counts
when the run has no landing; it leaves one run whose record says error and why, and still
calls no harness.  A line holding `<<` that bash reads as no heredoc runs as written.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, with tasks from taskfile.py and harnesses from fakeadapter.py that a
refused task never reaches.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

CEILING = ("4 done-when checks: a task has at most 3, one behaviour a reviewer holds in one "
           "read; split it")
HEREDOC = ("done-when line '{}' opens a heredoc, but each line runs as a command of its own: "
           "put the script in a file the change adds, or on one line")
BUDGET = ("{} 4 is over the budget: 3 rounds, then a run goes back to its orchestrator to "
          "split or re-scope")
NO_SECTION = "no `## Done when` section"
NO_BLOCK = "`## Done when` has no ```bash fenced command block"
EMPTY = "`## Done when` block is empty; done means commands that exit 0"
FOUR = ("true", "test -d .", "test -e .keep", "test -f .keep")
ONCE = (*FOUR[:3], "test -f .keep  # once")
# --no-merge in both, so a launch that is not refused never reaches a landing.
MODES = (("--no-merge",), ("--no-merge", "--bg"))


def project(cls):
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets")
    akconfig.write(cls.home, ["opus", "astra"])
    cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")


def entries(directory):
    return sorted(path.name for path in directory.iterdir()
                  if not path.name.startswith(".")) if directory.is_dir() else []


class RefusedBeforeAnythingStarts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project(cls)

    def assert_refused(self, task, sentence, *flags):
        for mode in MODES:
            with self.subTest(task=task.name, mode=mode):
                done = self.home.ak("run", str(task), *flags, *mode)
                self.assertEqual((done.code, done.err), (2, f"ak run: {sentence}\n"), done.out)
                self.assert_nothing_started()

    def assert_nothing_started(self):
        self.assertEqual(taskfile.runs(self.home), [])
        for kept in ("jobs", "wt"):
            self.assertEqual(entries(self.home.path / ".agentkit" / kept), [], kept)
        self.assertEqual((self.rig.branches(remote=False), self.rig.branches()),
                         (["main"], ["main"]))
        self.assertEqual({name: fake.n for name, fake in self.fakes.items()},
                         {"claude": 0, "codex": 0})

    def write(self, title, **kwargs):
        return taskfile.write(self.home, self.rig.path, title, **kwargs)

    def test_a_done_when_without_checks_in_a_bash_block_is_refused_naming_the_file(self):
        cases = {"No heading": ((), "", NO_SECTION),
                 "Prose only": ((), "## Done when\nthe tests pass\n", NO_BLOCK),
                 "Text fence": ((), "## Done when\n```text\ntrue\n```\n", NO_BLOCK),
                 "Empty fence": ((), "## Done when\n```bash\n```\n", EMPTY),
                 "Only comments": (("# nothing to check yet",), "", EMPTY)}
        for title, (done_when, body, sentence) in cases.items():
            task = self.write(title, done_when=done_when, body=body)
            self.assert_refused(task, f"{task}: {sentence}")

    def test_a_check_line_that_opens_a_heredoc_is_refused_naming_that_line(self):
        cases = {"Heredoc first": (("cat <<EOF", "x", "EOF"), "cat <<EOF"),
                 "Heredoc later": (("true", "sort <<-END", "END"), "sort <<-END")}
        for title, (done_when, line) in cases.items():
            self.assert_refused(self.write(title, done_when=done_when), HEREDOC.format(line))

    def test_more_than_three_rounds_is_refused_from_the_front_matter_or_the_flag(self):
        self.assert_refused(self.write("Four rounds", front={"rounds": 4}),
                            BUDGET.format("task rounds"))
        self.assert_refused(self.write("Plain task"), BUDGET.format("--rounds"),
                            "--rounds", "4")


class MoreThanThreeChecks(unittest.TestCase):
    """Five launches, each over the ceiling, in a project or a scratch task with no `repo:`."""

    CASES = {"Four checks": (True, FOUR, ("--no-merge",)),
             "Four checks in the background": (True, FOUR, ("--no-merge", "--bg")),
             "Three checks and a once line": (True, ONCE, ("--no-merge",)),
             "Scratch with four checks anyway": (False, FOUR, ("--anyway",)),
             "Scratch with a once line": (False, ONCE, ())}

    @classmethod
    def setUpClass(cls):
        project(cls)
        cls.launched = {}
        for title, (in_project, done_when, flags) in cls.CASES.items():
            task = taskfile.write(cls.home, cls.rig.path if in_project else None, title,
                                  done_when=done_when)
            before = taskfile.runs(cls.home)
            done = cls.home.ak("run", str(task), *flags)
            cls.launched[title] = done, [run for run in taskfile.runs(cls.home)
                                         if run not in before]

    def test_each_is_refused_with_exit_2_and_split_it(self):
        for title, (done, _) in self.launched.items():
            with self.subTest(title):
                self.assertEqual((done.code, done.err), (2, f"ak run: {CEILING}\n"), done.out)

    def test_each_leaves_one_run_whose_record_says_error_and_why(self):
        for title, (_, new) in self.launched.items():
            with self.subTest(title):
                self.assertEqual(len(new), 1, new)
                state = json.loads((new[0] / "run.json").read_text())
                self.assertEqual((state["state"], state["error"]), ("error", CEILING))
                lines = (new[0] / "result.md").read_text().splitlines()
                self.assertEqual(lines[0], f"# FAIL — {title}")
                self.assertIn("VERDICT: none", lines)
                self.assertIn(CEILING, lines)

    def test_no_harness_branch_or_worktree_is_started(self):
        self.assertEqual({name: fake.n for name, fake in self.fakes.items()},
                         {"claude": 0, "codex": 0})
        self.assertEqual((self.rig.branches(remote=False), self.rig.branches()),
                         (["main"], ["main"]))
        self.assertEqual(entries(self.home.path / ".agentkit" / "wt"), [])


class NoHeredocRunsAsWritten(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project(cls)
        cls.checks = ("cat <<< hi", "test $((1 << 2)) = 4", "test -f retry.txt")
        task = taskfile.write(cls.home, cls.rig.path, "Shift and here string",
                              done_when=cls.checks)
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    def test_a_here_string_or_a_shift_is_no_heredoc_and_each_line_runs(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        state = json.loads((self.run_dir / "run.json").read_text())
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        log = (self.run_dir / "round-1" / "donewhen.log").read_text()
        for check in self.checks:
            self.assertIn(f"$ {check}", log)
        self.assertEqual(self.fakes["claude"].n, 1)


if __name__ == "__main__":
    unittest.main()
