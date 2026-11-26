"""A job reruns a task that failed at its round budget with no review failing it only on an
executor a marked reviewer of another lab can review, while one of its builders is: with no
lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  astra builds a task whose done-when never
passes in its one round, and its review passes; its record is then the one integration leaves at
a spent round budget with the review pending (tests/test_task_files_one_job.py's round-shortfall
test), and a job whose launcher is gone, holding it as its one task, is resumed.  Where opus and
astra, on another provider, build and opus alone reviews, no rerun starts and no executor turn
runs on opus's harness: the task fails to the seat as it does with one worker.  Where astra and
nova, on astra's provider, build and astra alone reviews, the rerun starts on nova.  Black-box,
on the fixtures of tests/test_key_an_executor_has_another_labs_reviewer.py, the job's receipt
written by hand where ak keeps it.

The marks read are the failed run's.  Reviewer marks changed before the rerun launches are
not: the owner left that so on 26 Nov 2026 (the comment at `job_ladder`'s rotation).
"""

import json
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.akbin import owner
from test_key_writer_reviews_only_without_room import meter, record, roles, staged

JOB = "20261121-090000-acme"
SHORTFALL = ("done-when and review are pending at round 2, but the round budget (1) is spent; "
             "split or re-scope the task")


def resumed(case, models, workers, reviewers):
    """astra's run, ended at its spent round budget, resumed as a job's one task."""
    week = [meter(10, time.time() + 86400)]
    home = staged(case, models, reviewers, {"claude": week, "codex": week}, workers=workers,
                  claude="work", codex="work")
    task = taskfile.write(home, case.rig.path, front={"rounds": 1},
                          done_when=("test -f missing",))
    home.ak("run", str(task), "--exec", "astra", "--no-merge", timeout=300)
    case.run_dir = taskfile.only_run(home)
    # as integration leaves a review it invalidated at the last round
    (case.run_dir / "run.json").write_text(json.dumps({
        **record(case.run_dir), "state": "exhausted", "verdict": "FAIL", "error": SHORTFALL,
        "review_pending": {"round": 2, "reason": "integration moved main"}}))
    gone = subprocess.Popen(["sleep", "60"])
    launched = owner(gone.pid)
    gone.kill()
    gone.wait()
    receipt = home.write(f".agentkit/jobs/{JOB}/job.json", {
        "job_id": JOB, "seat": None, "started_at": time.time(), "finished_at": None,
        "parallel": None, "opts": {"--no-merge": True}, **launched,
        "tasks": [{"name": task.name, "title": "Add retry file", "state": "running",
                   "run_id": case.run_dir.name, "task_file": str(task)}]})
    case.done = home.ak("run", "resume", JOB, timeout=300)
    case.task, = json.loads(receipt.read_text())["tasks"]


class NoRerunOnABuilderOnlyItsOwnLabReviews(unittest.TestCase):
    """opus and astra, on another provider, build; opus alone reviews."""

    @classmethod
    def setUpClass(cls):
        resumed(cls, ["opus", "astra"], ["opus", "astra"], ["opus"])

    def test_no_rerun_starts_and_no_executor_turn_runs_on_opus_s_harness(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(taskfile.runs(self.home), [self.run_dir])
        self.assertEqual(roles(self.fakes["claude"]), ["reviewer"])
        self.assertNotIn("rerun_attempted", self.task)

    def test_the_task_fails_to_the_seat_as_with_one_worker(self):
        self.assertEqual((self.task["state"], self.task["run_id"]), ("failed", self.run_dir.name))


class TheRerunStartsOnTheReviewersOtherModel(unittest.TestCase):
    """astra and nova, on astra's provider, build; astra alone reviews."""

    @classmethod
    def setUpClass(cls):
        resumed(cls, {"astra": {}, "nova": {"harness": "codex", "model": "gpt-nova-1"}},
                ["astra", "nova"], ["astra"])

    def test_the_rerun_starts_on_nova(self):
        self.assertEqual(self.task["rerun_executor"], "nova")
        self.assertNotEqual(self.task["run_id"], self.run_dir.name)
        self.assertIn(("executor", "gpt-nova-1"),
                      [(run["role"], run["argv"][0]) for run in self.fakes["codex"].runs()])


if __name__ == "__main__":
    unittest.main()
