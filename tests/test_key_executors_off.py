"""Executors off leaves every build to the orchestrator, with its own PR size gate.

Black-box: AK_BIN reads host settings or project front matter and launches from a seat.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class ExecutorsOff(unittest.TestCase):
    def prepare(self, front, **numbers):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"], settings={} if front else numbers)
        rules = "---\ntests: none\nhealth: none\nusers: none\n"
        if front:
            rules += "".join(f"{key}: {value}\n" for key, value in numbers.items())
        self.rig = Rig(self.home, "widgets", files={"AGENTS.md": rules + "---\nA project.\n"})
        self.rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        Seat(self.home, "acme", model="opus", cwd=self.rig.path, alive=False, planned=True)

    def run_from_seat(self, *args):
        return self.home.ak("run", *args, cwd=self.rig.path,
                            env={"AGENTKIT_SESSION": "acme"}, timeout=300)

    def turns(self):
        return [turn for fake in self.fakes.values() for turn in fake.runs()]

    def test_project_seat_help_says_executors_are_off(self):
        self.prepare(True, executor_lines=0, orchestrator_lines=2)
        Seat(self.home, "maker", model="opus", cwd=self.home.path, alive=False,
             record={"repo": str(self.rig.path)})
        for seat, cwd in (("acme", self.rig.path), ("maker", self.home.path)):
            with self.subTest(seat=seat):
                shown = self.home.ak("run", "--help", cwd=cwd, env={"AGENTKIT_SESSION": seat})
                self.assertEqual(shown.code, 0, shown.err)
                self.assertIn("Executors are off; the orchestrator builds every change itself.", shown.out)
                self.assertIn("at most 2 added lines per PR; split larger changes", shown.out)
                self.assertNotIn("Task size:", shown.out)
                self.assertNotIn("as a task and an executor builds it", shown.out)

    def test_negative_executor_lines_are_refused_naming_zero_as_the_floor(self):
        for front in (False, True):
            with self.subTest(front=front):
                self.prepare(front, executor_lines=-1)
                done = self.run_from_seat(str(taskfile.write(self.home, self.rig.path)))
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn("executor_lines must be a whole number of at least 0", done.err)
                self.assertIn("the most added lines a first review reads", done.err)
                self.assertEqual((taskfile.runs(self.home), self.turns()), ([], []))

    def test_tasks_are_refused_before_any_executor_starts(self):
        for front in (False, True):
            with self.subTest(front=front):
                self.prepare(front, executor_lines=0)
                task = str(taskfile.write(self.home, self.rig.path))
                other = str(taskfile.write(self.home, self.rig.path, "Other change"))
                for args in ((task,), (task, "--bg"), (task, other)):
                    done = self.run_from_seat(*args)
                    self.assertNotEqual(done.code, 0, done.out + done.err)
                    self.assertIn("executor_lines", done.err)
                    self.assertIn("orchestrator builds every change itself", done.err)
                Seat(self.home, "acme", model="opus", cwd=self.rig.path, alive=False,
                     planned=True, record={"workers": []})
                done = self.run_from_seat(task)
                self.assertNotEqual(done.code, 0, done.out + done.err)
                self.assertIn("executor_lines", done.err)
                self.assertEqual((taskfile.runs(self.home), self.turns()), ([], []))

    def test_own_prs_are_reviewed_under_the_orchestrator_limit_and_split_above_it(self):
        for front in (False, True):
            with self.subTest(front=front):
                self.prepare(front, executor_lines=0, orchestrator_lines=2)
                gh = GitHub(self.home)
                for branch, count in (("small", 2), ("large", 3)):
                    self.rig.branch(branch, {"contrib.txt": "row\n" * count})
                    url = gh.open_pr(self.rig, branch, title=branch)
                    done = self.run_from_seat("--review-pr", url, "--no-merge")
                    if count == 2:
                        self.assertEqual(done.code, 0, done.out + done.err)
                        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
                        self.assertEqual((state["verdict"], state["own_pr"]), ("PASS", True))
                    else:
                        self.assertNotEqual(done.code, 0, done.out + done.err)
                        self.assertIn("at most 2 added lines", done.err)
                        self.assertIn("split it", done.err.lower())
                self.assertEqual([turn["role"] for turn in self.turns()], ["reviewer"])

    def test_both_builders_off_are_refused_wherever_the_numbers_are_read(self):
        for front in (False, True):
            with self.subTest(front=front):
                self.prepare(front, executor_lines=0, orchestrator_lines=0)
                task = str(taskfile.write(self.home, self.rig.path))
                gh = GitHub(self.home)
                self.rig.branch("small", {"contrib.txt": "row\n"})
                url = gh.open_pr(self.rig, "small", title="Small change")
                for args in ((task,), ("--review-pr", url, "--no-merge")):
                    done = self.run_from_seat(*args)
                    self.assertNotEqual(done.code, 0, done.out + done.err)
                    for key in ("executor_lines", "orchestrator_lines"):
                        self.assertIn(key, done.err)
                self.assertEqual((taskfile.runs(self.home), self.turns()), ([], []))

    def test_host_and_project_cannot_turn_off_the_other_builder(self):
        for host, project in (("executor_lines", "orchestrator_lines"),
                              ("orchestrator_lines", "executor_lines")):
            with self.subTest(host=host):
                self.prepare(True, **{project: 0})
                akconfig.write(self.home, ["opus", "astra"], settings={host: 0})
                done = self.run_from_seat(str(taskfile.write(self.home, self.rig.path)))
                self.assertNotEqual(done.code, 0, done.out + done.err)
                for key in (host, project):
                    self.assertIn(key, done.err)
                self.assertEqual((taskfile.runs(self.home), self.turns()), ([], []))


if __name__ == "__main__":
    unittest.main()
