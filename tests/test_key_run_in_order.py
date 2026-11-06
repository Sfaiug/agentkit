"""`ak run a.md b.md c.md --in-order` starts each task once the one before it merged.

The first task that ends without a merge ends the job, the rest never start, and the seat hears
the job's one line and nothing of its tasks, on a project with `health:` too.  Black-box through
AK_BIN: fake adapters and GitHub in acme/widget, and the seat that launched the job.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable, rerun_boxed
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

REFUSAL = ("an ordered job cuts each task from its repository's default branch, where the one "
           "before it merged: drop base:, target: and from:")

def wait_for(read, bound=180):
    deadline = time.monotonic() + bound
    while not (seen := read()):
        if time.monotonic() > deadline:
            raise AssertionError("the job did not reach its expected state")
        time.sleep(.1)
    return seen


def launch(case, health, executor, reviewer, front=(), repo=None, then=lambda tasks: None):
    """Tasks a, b and c launched in order from the seat, followed until the seat has the job's
    line; `front` is each task's front matter, `repo` its `repo:` if not the rig's, `then` what
    the test does to the task files once the job is under way.  `executor` may be a function of
    the directory the fake adapters share with the test."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    akconfig.write(home, ["opus", "astra"])
    case.rig = rig = Rig(home, "widget",
                         files={"AGENTS.md": f"---\ntests: true\nhealth: {health}\nusers: none\n---\n"})
    case.gh = GitHub(home)
    case.seat = Seat(home, "acme", cwd=rig.path, planned=True,
                     record={"workers": ["opus"], "reviewers": ["astra"]})
    shared = home.root / "adapters"
    case.fakes = fakeadapter.install(home, codex=reviewer, claude=executor(shared)
                                     if callable(executor) else executor)
    tasks = [taskfile.write(home, repo or rig.path, f"Add {name}", name=name, front=dict(front),
                            done_when=(f"test -f {name}.txt",)) for name in "abc"]
    done = home.ak("run", *map(str, tasks), "--in-order", "--bg",
                   env={"AGENTKIT_SESSION": case.seat.name})
    assert done.code == 0, done.out + done.err
    case.directory, = (home.path / ".agentkit/jobs").iterdir()
    then(tasks)
    wait_for(lambda: (case.job().get("card_sent") or {}).get("kind") == "handback")


def write(name):
    return {**fakeadapter.WORK, "write": {f"{name}.txt": name}}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class Case(unittest.TestCase):
    @classmethod
    def job(cls):
        return json.loads((cls.directory / "job.json").read_text())

    def run_of(self, name):
        task = next(task for task in self.job()["tasks"] if task["name"] == f"{name}.md")
        return json.loads((self.home.path / ".agentkit/runs" / task["run_id"] / "run.json")
                          .read_text())

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def notices(self):
        """What the seat was told, each line up to its result's path; the stop rule's
        `continue` to a seat idle at its prompt tells it nothing."""
        return [line.split(". Result: ")[0] for line in self.seat.lines() if line != "continue"]


class EveryTaskMerges(Case):
    @classmethod
    def setUpClass(cls):
        launch(cls, "true", [write(name) for name in "abc"], "pass")

    def test_each_task_starts_on_the_merge_of_the_one_before(self):
        merges = {pr["url"]: pr["merge"]["commit"] for pr in self.gh.prs()}
        for before, after in ("ab", "bc"):
            with self.subTest(after):
                self.assertEqual(self.run_of(after)["base_sha"],
                                 merges[self.run_of(before)["pr"]])
        self.assertEqual([task["state"] for task in self.job()["tasks"]], ["merged"] * 3)

    def test_the_jobs_line_is_the_seats_one_wake_though_each_task_went_live(self):
        for name in "abc":
            wait_for(lambda: self.tick() or self.run_of(name).get("live_at"))
        self.tick()
        self.assertEqual(self.notices(),
                         [f"job {self.directory.name}: all 3 tasks finished"])


class ATaskThatFailsEndsTheJob(Case):
    @classmethod
    def setUpClass(cls):
        # b's reviewer finds the fixture's defect in its one round; c is never started
        launch(cls, "none", [write("a"), {**fakeadapter.WORK, "write": {
            "b.txt": "b", "retry.txt": "x"}}], ["pass", "fail"], front={"rounds": 1})

    def test_the_rest_never_start_and_the_line_names_them(self):
        self.assertEqual([(task["state"], bool(task["run_id"])) for task in self.job()["tasks"]],
                         [("merged", True), ("failed", True), ("skipped", False)])
        self.assertEqual(self.fakes["claude"].n, 2)
        self.assertEqual(len(taskfile.runs(self.home)), 2)
        self.tick()
        self.assertEqual(self.notices(),
                         [f"job {self.directory.name}: b.md: FAIL after 1 rounds: needs you; "
                          "not started: c.md"])


class ATaskThatPassesUnmergedEndsTheJob(Case):
    @classmethod
    def setUpClass(cls):
        # a scratch task passes and merges nothing, so neither b nor c starts
        launch(cls, "none", write("a"), "pass", repo="none")

    def test_the_rest_never_start(self):
        self.assertEqual([task["state"] for task in self.job()["tasks"]],
                         ["passed", "skipped", "skipped"])
        self.tick()
        self.assertEqual(self.notices(), [f"job {self.directory.name}: a.md: PASS, passed after "
                                          "1 rounds; not started: b.md, c.md"])

    def test_a_task_naming_its_own_branch_is_refused_and_nothing_starts(self):
        first = taskfile.write(self.home, self.rig.path, "Add d", name="d")
        for key in ("base", "target", "from"):
            with self.subTest(key):
                task = taskfile.write(self.home, self.rig.path, "Add e", name="e",
                                      front={key: "main"})
                done = self.home.ak("run", str(first), str(task), "--in-order")
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertTrue(done.err.endswith(f": {REFUSAL}\n"), done.err)
                self.assertEqual(list((self.home.path / ".agentkit/jobs").iterdir()),
                                 [self.directory])


class ATaskGivenABranchOfItsOwnWhileQueuedNeverRuns(Case):
    @classmethod
    def setUpClass(cls):
        def hold(shared):
            return {**write("a"), "sh": f"for i in $(seq 1200); do [ -f {shared}/release ] && "
                                        "break; sleep .1; done"}

        def edit(tasks):
            # b, still queued behind a, is told to continue a branch; a then goes on to merge
            wait_for(lambda: cls.fakes["claude"].n)
            tasks[1].write_text(tasks[1].read_text().replace("---\n# ", "from: main\n---\n# ", 1))
            (cls.fakes["claude"].dir / "release").touch()
        launch(cls, "none", hold, "pass", then=edit)

    def test_it_is_refused_at_its_start_and_the_rest_never_start(self):
        self.assertEqual([(task["state"], bool(task["run_id"])) for task in self.job()["tasks"]],
                         [("merged", True), ("blocked", False), ("skipped", False)])
        self.assertEqual(self.fakes["claude"].n, 1)
        self.tick()
        self.assertEqual(self.notices(), [f"job {self.directory.name}: b.md: BLOCKED: {REFUSAL}; "
                                          "not started: c.md"])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
