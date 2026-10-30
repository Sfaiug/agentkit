"""A task that parses but cannot start ends in a run of its own, in state error, with its reason.

Four done-when checks (`split it`), a merge strategy ak has no way to land with, or a `repo:`
that is no git repository each refuse the run before any model turn, and the refusal is not
only a line on the terminal: it leaves `runs/<id>/run.json` in state `error` carrying the
reason, a result.md that says why, and a row `ak run status --json` lists, so a seat that
launched it in the background, the status screen and a later version all read the same
answer.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with tasks from taskfile.py and scripted harnesses from
fakeadapter.py that count every turn.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home

SPLIT_IT = ("4 done-when checks: a task has at most 3, one behaviour a reviewer holds in one "
            "read; split it")
MERGE = "merge must be one of squash, merge, rebase (got 'fast')"


class RefusedTasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.missing = cls.home.path / "code" / "gone"
        tasks = {"checks": taskfile.write(cls.home, "none", "Fix api", done_when=("true",) * 4),
                 "merge": taskfile.write(cls.home, "none", "Fix beta", front={"merge": "fast"},
                                         done_when=("true",)),
                 "repo": taskfile.write(cls.home, cls.missing, "Fix acme")}
        cls.task, cls.done, cls.run_dir, cls.state = {}, {}, {}, {}
        for case, task in tasks.items():
            before = set(taskfile.runs(cls.home))
            cls.task[case], cls.done[case] = task, cls.home.ak("run", str(task), timeout=300)
            # exactly one run directory per launch, found on disk and not in what ak printed
            added = set(taskfile.runs(cls.home)) - before
            assert len(added) == 1, f"{case}: one new run expected, found {sorted(added)}"
            cls.run_dir[case] = added.pop()
            cls.state[case] = json.loads((cls.run_dir[case] / "run.json").read_text())

    def printed(self, case):
        done = self.done[case]
        return (done.out + done.err).splitlines()

    def test_each_refusal_exits_2_and_records_the_run_in_error(self):
        for case in self.task:
            with self.subTest(case):
                done, state = self.done[case], self.state[case]
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertEqual(state["state"], "error")
                self.assertIsNone(state["verdict"])
                self.assertEqual(state["run_id"], self.run_dir[case].name)
                # what the terminal said is what the record keeps
                self.assertIn(f"ak run: {state['error']}", self.printed(case))

    def test_four_checks_are_refused_with_split_it(self):
        self.assertEqual(self.state["checks"]["error"], SPLIT_IT)

    def test_an_unknown_merge_strategy_is_refused_naming_the_three_there_are(self):
        self.assertTrue(self.state["merge"]["error"].endswith(f": {MERGE}"),
                        self.state["merge"]["error"])

    def test_a_repo_that_is_no_git_repository_is_refused_naming_it(self):
        self.assertTrue(self.state["repo"]["error"].endswith(
            f": repo {self.missing} is not a git repository"), self.state["repo"]["error"])

    def test_no_model_turn_runs_and_github_is_never_asked(self):
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))
        self.assertEqual(self.home.calls("gh"), [])

    def test_a_run_refused_at_preflight_keeps_who_what_and_when(self):
        state = self.state["checks"]
        self.assertEqual(state["title"], "Fix api")
        for key in ("queued_at", "started_at", "finished_at"):
            with self.subTest(key):
                self.assertIsInstance(state[key], (int, float))
        self.assertIsInstance(state["launch_opts"], dict)
        self.assertIn("--rounds", state["launch_opts"])
        self.assertIsInstance(state["process_identity"], dict)
        self.assertEqual(state["task_file"], str(self.task["checks"]))
        self.assertEqual((self.run_dir["checks"] / "task.md").read_bytes(),
                         self.task["checks"].read_bytes())

    def test_a_scratch_run_refused_past_preflight_records_what_it_would_have_delivered(self):
        state = self.state["merge"]
        self.assertEqual({key: state.get(key) for key in (
            "title", "scratch", "repo", "no_merge", "task_checks")}, {
            "title": "Fix beta", "scratch": True, "repo": None, "no_merge": True,
            "task_checks": 1})
        for key in ("task_words", "task_points"):
            with self.subTest(key):
                self.assertIsInstance(state[key], int)
        for key in ("queued_at", "started_at", "finished_at"):
            with self.subTest(key):
                self.assertIsInstance(state[key], (int, float))
        self.assertIn("--rounds", state["launch_opts"])
        self.assertIsInstance(state["process_identity"], dict)
        self.assertEqual(state["task"], str(self.run_dir["merge"] / "task.md"))
        self.assertTrue(Path(state["task"]).is_file())

    def test_result_md_says_why_the_run_stopped_and_how_to_launch_it_again(self):
        titles = {"checks": "Fix api", "merge": "Fix beta", "repo": "Fix acme"}
        for case, title in titles.items():
            with self.subTest(case):
                run_dir = self.run_dir[case]
                lines = (run_dir / "result.md").read_text().splitlines()
                self.assertEqual(lines[4], f"# FAIL — {title}")
                for line in ("VERDICT: none", "## Why this run stopped", self.state[case]["error"],
                             f"relaunch: ak run {run_dir / 'task.md'}"):
                    self.assertIn(line, lines)

    def test_run_status_json_lists_each_refused_run_as_its_record_says(self):
        done = self.home.ak("run", "status", "--json")
        self.assertEqual(done.code, 0, done.err)
        rows = {row["run_id"]: row for row in json.loads(done.out)}
        for case, run_dir in self.run_dir.items():
            with self.subTest(case):
                row = rows[run_dir.name]
                self.assertEqual((row["state"], row["error"]),
                                 ("error", self.state[case]["error"]))
                self.assertEqual(row["paths"]["record"], str(run_dir / "run.json"))
                self.assertEqual(row["paths"]["result"], str(run_dir / "result.md"))


if __name__ == "__main__":
    unittest.main()
