"""A project's AGENTS.md front matter sets its own `review_rounds`, `executor_lines` and `orchestrator_lines`.

A run holds to what was read when its directory was made, and a bad number refuses the launch
before one is.  A review of a project with no checkout here runs on the host's.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
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

# `false` fails on the change and on its base alike: a proof only a dispute answers.
FAILING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}
BUILD = {"write": {"retry.txt": "row\n" * 150}, "commit": "the change", "hand_in": [["done"]],
         "final": "## Summary\nwrote it"}


def over(asked, budget):
    return (f"ak run: --rounds {asked} is over the budget: {budget} rounds, then a run goes back "
            "to its orchestrator to split or re-scope\n")


def front(**numbers):
    return {"AGENTS.md": "---\ntests: none\nhealth: none\nusers: none\n" + "".join(f"{key}: {value}\n" for key, value in numbers.items())
                         + "---\nA project.\n"}


def host(case, name, claude="pass", codex="pass", **numbers):
    case.home = Home()
    case.addClassCleanup(case.home.close)
    akconfig.write(case.home, ["opus", "astra"], settings={"review_rounds": 5})
    case.fakes = fakeadapter.install(case.home, claude=claude, codex=codex)
    rig = Rig(case.home, name, files=front(**numbers))
    rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return rig


def launched(home, *argv, **kw):
    before = set(taskfile.runs(home))
    done = home.ak("run", *argv, timeout=300, **kw)
    run_dir, = set(taskfile.runs(home)) - before
    return done, run_dir, json.loads((run_dir / "run.json").read_text())


class Rounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rig = host(cls, "widgets", ["work", "dispute"], FAILING, review_rounds=2)
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.refused = cls.home.ak("run", str(task), "--rounds", "3", timeout=60)
        cls.made = taskfile.runs(cls.home)
        cls.done, cls.run_dir, cls.state = launched(cls.home, str(task), "--no-merge")
        # the default branch moves under the ended run: its budget stays what was read
        cls.rig.commit(front(review_rounds=7), "more rounds")
        cls.rig.git("fetch", "-q", "origin")
        cls.resumed = cls.home.ak("run", "resume", cls.run_dir.name, "--rounds", "3", timeout=60)
        # a record from before the numbers were kept stays on the host's
        record = cls.run_dir / "run.json"
        record.write_text(json.dumps({k: v for k, v in cls.state.items() if k != "policy"}))
        cls.legacy = cls.home.ak("run", "resume", cls.run_dir.name, "--rounds", "8", timeout=60)
        cls.stale = cls.home.ak("run", str(task), "--rounds", "8", timeout=60,
                                env={"AGENTKIT_RUN_DIR": str(cls.home.root / "gone")})
        # a branch the owner stands on says nothing: the default branch does
        cls.rig.git("checkout", "-q", "-b", "side")
        cls.rig.commit(front(review_rounds=9), "on a side branch", push=False)
        cls.side = cls.home.ak("run", str(task), "--rounds", "8", timeout=60)
        job = cls.home.path / ".agentkit/jobs/acme-job"
        job.mkdir(parents=True)
        (job / "job.json").write_text(json.dumps({"tasks": [], "cwd": str(cls.rig.path)}))
        cls.job = cls.home.ak("run", "resume", job.name, "--rounds", "8", timeout=60)
        cls.fakes["claude"].behave("blocked")
        cls.above = launched(cls.home, str(task), "--no-merge", "--anyway", "--rounds", "6")[2]
        plain = Rig(cls.home, "gears")      # no project override: its branch says nothing either
        plain.git("checkout", "-q", "-b", "side")
        plain.commit(front(review_rounds=1), "on a side branch", push=False)
        cls.plain = launched(cls.home, str(taskfile.write(cls.home, plain.path, "Other")), "--no-merge")[2]

    def test_a_rounds_over_the_project_s_is_refused_with_no_run_made(self):
        self.assertEqual((self.refused.code, self.refused.err), (2, over(3, 2)))
        self.assertEqual(self.made, [])

    def test_a_reviewer_failing_each_round_ends_the_run_fail_after_two_of_two(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["verdict"], self.state["rounds"]), ("FAIL", 2))
        self.assertIn("rounds: 2 of 2", (self.run_dir / "result.md").read_text().splitlines())

    def test_a_run_keeps_its_budget_and_the_default_branch_answers_not_the_one_checked_out(self):
        self.assertEqual((self.resumed.code, self.resumed.err), (2, over(3, 2)))
        self.assertEqual((self.side.code, self.side.err), (2, over(8, 7)))
        self.assertEqual((self.job.code, self.job.err), (2, over(8, 7)))
        self.assertEqual((self.stale.code, self.stale.err), (2, over(8, 7)))
        self.assertEqual((self.legacy.code, self.legacy.err), (2, over(8, 5)))

    # A project overrides any in its front matter. [30 Oct 2026]
    def test_a_project_may_raise_the_host_s_and_one_without_the_line_reads_it(self):
        self.assertEqual((self.above["rounds"], self.plain["rounds"]), (6, 5))


class Lines(unittest.TestCase):
    def test_review_lines_and_seat_lines_hold_for_the_project(self):
        rig = host(self, "widgets", BUILD, executor_lines=120, orchestrator_lines=20)
        _, _, state = launched(self.home, str(taskfile.write(self.home, rig.path)), "--no-merge")
        self.assertIn("a first review takes at most 120; split it", state["error"])
        self.assertIn("a first review takes at most 120", self.fakes["claude"].runs()[0]["hand_ins"][0]["err"])
        gh = GitHub(self.home)
        Seat(self.home, "acme", model="opus", cwd=rig.path, alive=False, planned=True)
        rig.branch("big", {"contrib.txt": "line\n" * 25})
        done = self.home.ak("run", "--review-pr", gh.open_pr(rig, "big", title="big"), "--no-merge",
                            cwd=rig.path, env={"AGENTKIT_SESSION": "acme"}, timeout=300)
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn("too big for the seat, which builds at most 20 added lines", done.err)


class ReviewWithNoCheckout(unittest.TestCase):
    def test_the_first_runs_on_the_host_s_and_the_next_reads_the_checkout_it_cloned(self):
        rig = host(self, "widgets", review_rounds=2)
        gh = GitHub(self.home)
        away = self.home.path / "elsewhere"
        Seat(self.home, "acme", model="opus", cwd=away, alive=False, planned=True)
        rig.branch("first", {"first.txt": "first\n"})
        rig.branch("second", {"second.txt": "second\n"})
        rig.path.rename(away)
        for branch, rounds in (("first", 5), ("second", 2)):
            done, _, state = launched(self.home, "--review-pr", gh.open_pr(rig, branch, title=branch),
                                      "--no-merge", cwd=away, env={"AGENTKIT_SESSION": "acme"})
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(state["rounds"], rounds)


class Refused(unittest.TestCase):
    def test_a_number_nobody_could_mean_refuses_the_launch_with_no_run_directory(self):
        review, seat = "the most added lines a first review reads", "the most added lines an orchestrator builds"
        for numbers, why in (
                ({"executor_lines": "abc"}, f'executor_lines must be a whole number of at least 0 or "no limit", {review} (got \'abc\')'),
                ({"orchestrator_lines": "abc"}, f'orchestrator_lines must be a whole number of at least 0 or "no limit", {seat} (got \'abc\')')):
            with self.subTest(numbers=numbers):
                rig = host(self, "widgets", **numbers)
                done = self.home.ak("run", str(taskfile.write(self.home, rig.path)), timeout=60)
                self.assertEqual((done.code, done.err), (2, f"ak run: {rig.path / 'AGENTS.md'}: {why}\n"))
                self.assertEqual(taskfile.runs(self.home), [])


if __name__ == "__main__":
    unittest.main()
