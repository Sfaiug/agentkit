"""A done-when check that fails the same way after a fix round ends the run BLOCKED.

When a check fails, the round gives the executor one fix turn shown its output, then runs the
checks again.  The first round's failure is only recorded.  When a later round, after its fix
turn, leaves the same checks failing with the same last line, more turns would buy the same
answer: the task or its checks are wrong, so the run stops there, before that round's review
and without a third round, naming each such check and what it printed.  The executor's work
changes on every turn here, so it is the failure standing still that ends the run, not the
code.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
on a project from gitrig.py with scripted harnesses from fakeadapter.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PASSING = "test -f other.txt"
FAILING = "test -f retry.txt || (echo 'retry.txt is missing'; exit 1)"
BLOCKED = ("the same checks fail the same way after a fix round: "
           "the task or its checks are wrong")


def attempt(n):
    """A turn that changes the work, but never writes the file the failing check wants."""
    return {"write": {"other.txt": f"attempt {n}\n"}, "commit": f"attempt {n}",
            "final": f"## Summary\nattempt {n}", "hand_in": [["done"]]}


class SameFailureBlocks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=[attempt(n) for n in range(1, 5)],
                                        codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file",
                              done_when=(PASSING, FAILING))
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_ends_blocked_in_its_second_round_before_that_round_s_review(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertTrue(self.done.out.rstrip("\n").endswith(
            f"FAIL -> {self.run_dir / 'result.md'}"), self.done.out)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "merged")},
                         {"state": "blocked", "verdict": "BLOCKED", "merged": False})
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL"])
        log = [re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line)
               for line in (self.run_dir / "log.txt").read_text().splitlines()]
        steps = [line for line in log if line.startswith(
            ("done-when: FAILED", "done-when: all passed", "done-when after fix", "BLOCKED",
             "round "))]
        self.assertEqual(steps, [
            "done-when: FAILED", "done-when after fix: still FAILING", "round 1 verdict: FAIL",
            "done-when: FAILED", "done-when after fix: still FAILING", f"BLOCKED {BLOCKED}"])

    def test_no_turn_runs_after_the_block(self):
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer", "fixer", "fixer"])
        self.assertEqual(self.fakes["codex"].n, 1)
        self.assertFalse((self.run_dir / "round-2/reviewer").exists())
        self.assertFalse((self.run_dir / "round-3").exists())
        # the last fix turn's work is there: the failure stood still while the code moved
        worktree = Path(self.state["worktree"])
        self.assertEqual((worktree / "other.txt").read_text(), "attempt 4\n")

    def test_each_fix_turn_is_shown_the_failing_check_and_what_it_printed(self):
        for round_dir in ("round-1", "round-2"):
            with self.subTest(round_dir):
                prompt = (self.run_dir / round_dir / "fixer/prompt.md").read_text()
                self.assertIn(f"$ {FAILING}\n[exit 1]\nretry.txt is missing", prompt)
                checks = (self.run_dir / round_dir / "donewhen.log").read_text()
                self.assertIn(f"$ {PASSING}\n[exit 0]", checks)
                self.assertIn(f"$ {FAILING}\n[exit 1]\nretry.txt is missing", checks)

    def test_result_md_names_only_the_check_that_failed_identically_and_its_output(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# BLOCKED — Add retry file")
        self.assertIn("VERDICT: BLOCKED", lines)
        start = lines.index("## Blocked")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
        self.assertEqual([line for line in lines[start:end] if line], [
            "## Blocked", BLOCKED, "The checks that failed identically twice:",
            f"- `{FAILING}` — retry.txt is missing"])


if __name__ == "__main__":
    unittest.main()
