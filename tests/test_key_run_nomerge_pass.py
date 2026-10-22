"""A --no-merge task whose work passes review ends PASS, with its whole record and nothing pushed.

`ak run task.md --no-merge` is how work is tried without delivering it: the executor's commits
stay on the run's branch in a kept worktree, the origin and GitHub are never touched, and the
run directory keeps what each turn was told, said and handed in, with result.md saying what
happened in a person's words.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py, a task from
taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class NoMergePass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.origin_refs = cls.rig.origin("for-each-ref")
        cls.done = cls.home.ak("run", str(cls.task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_work_passes_on_a_branch_of_its_own_and_nothing_is_pushed(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        run_id = self.run_dir.name
        self.assertRegex(run_id, r"^\d{8}-\d{4}-add-retry-file$")
        # The last line a person reads in the foreground is where the whole result is.
        self.assertTrue(self.done.out.rstrip("\n").endswith(str(self.run_dir / "result.md")),
                        self.done.out)
        worktree = self.home.path / ".agentkit/wt" / run_id
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "no_merge", "merged", "pr", "scratch", "executor", "reviewer",
            "rounds", "branch", "worktree")}, {
            "state": "pass", "verdict": "PASS", "no_merge": True, "merged": False, "pr": None,
            "scratch": False, "executor": "opus", "reviewer": "astra", "rounds": 3,
            "branch": "ak/add-retry-file", "worktree": str(worktree)})
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])
        tree = self.home.run("git", "-C", str(worktree), "ls-tree", "--name-only", "HEAD")
        self.assertIn("retry.txt", tree.out.split())
        self.assertIn("ak/add-retry-file", self.rig.branches(remote=False))
        self.assertEqual(self.rig.origin("for-each-ref"), self.origin_refs)
        self.assertFalse([call for call in self.home.calls("gh")
                          if call[:2] in (["pr", "create"], ["pr", "merge"])])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))

    def test_the_run_keeps_the_task_and_what_each_turn_was_told_said_and_handed_in(self):
        expected = ["task.md", "run.json", "log.txt", "result.md", "round-1/donewhen.log"]
        expected += [f"round-1/executor/{name}" for name in
                     ("prompt.md", "final.md", "hand-in.jsonl", "session_id")]
        expected += [f"round-1/reviewer/{name}" for name in
                     ("prompt.md", "final.md", "hand-in.jsonl", "findings.json")]
        for name in expected:
            with self.subTest(name):
                self.assertTrue((self.run_dir / name).is_file())
        self.assertEqual((self.run_dir / "task.md").read_bytes(), self.task.read_bytes())
        executor = self.run_dir / "round-1/executor"
        self.assertEqual((executor / "session_id").read_text().strip(), "sid-claude-1")
        rows = [json.loads(line) for line in (executor / "hand-in.jsonl").read_text().splitlines()]
        self.assertEqual((rows[0]["kind"], rows[0]["role"]), ("turn", "executor"))
        self.assertEqual(rows[-1], {"kind": "done"})
        checks = (self.run_dir / "round-1/donewhen.log").read_text()
        self.assertIn("$ test -f retry.txt", checks)
        self.assertIn("[exit 0]", checks)

    def test_result_md_says_pass_not_merged_and_the_rounds_it_took(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# PASS, not merged: --no-merge — Add retry file")
        for line in ("VERDICT: PASS", "rounds: 1 of 3", "pr: (none)", "merged: no"):
            self.assertIn(line, lines)
        branch = [line for line in lines if line.startswith("branch:")]
        self.assertEqual(len(branch), 1, lines)
        self.assertIn("ak/add-retry-file", branch[0])


if __name__ == "__main__":
    unittest.main()
