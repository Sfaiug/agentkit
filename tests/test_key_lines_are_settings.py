"""The added lines ak counts are the host's settings: `executor_lines` and `orchestrator_lines`.

Set, lower or higher than ak's default, `executor_lines` is what a task's first review takes and
what its executor's done is held to, and `orchestrator_lines` is the most a seat's own pull request
adds.  Unset, they read 300 and 50.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py, a task
from taskfile.py, scripted harnesses from fakeadapter.py, the seat of akseat.py and the GitHub
of fakegh.py; this test fails against `/bin/false`.
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

TAIL = "(generated files aside; deletions never count): a first review takes at most"
# `false` fails on the change and on its base alike: a proof only a dispute answers.
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}


def rows(count):
    return "".join(f"row {k:04d} of the retry table\n" for k in range(count))


def build(lines):
    """An executor turn adding `lines` lines."""
    return {"write": {"retry.txt": rows(lines)}, "commit": "the change",
            "final": "## Summary\nwrote it", "hand_in": [["done"]]}


# title: (config.toml's settings, the executor's turns then the fixer's, the reviewer's)
TASKS = {
    "Cut to 120": ({"executor_lines": 120}, [build(150)], ["pass"]),
    "Left at 300": ({}, [build(301)], ["pass"]),
    "Raised to 500": ({"executor_lines": 500}, [build(350), "dispute"], [FINDING, "concede"]),
}
# branch: (config.toml's settings, the lines its pull request adds)
PULLS = {
    "cut-to-20": ({"orchestrator_lines": 20}, 25),
    "left-at-50": ({}, 51),
    "raised-to-100": ({"orchestrator_lines": 100}, 60),
    "raised-to-500": ({"orchestrator_lines": 500}, 400),
}


def reviews(fakes):
    """Reviewer turns every harness has taken so far."""
    return sum(turn["role"] == "reviewer" for fake in fakes.values() for turn in fake.runs())


def prepared(case):
    case.home = Home()
    case.addClassCleanup(case.home.close)
    case.rig = Rig(case.home, "widgets")
    akconfig.write(case.home, ["opus", "astra"])
    case.fakes = fakeadapter.install(case.home, claude="pass", codex="pass")


# A first review's added lines are settings on the settings screen. [30 Oct 2026]
class TaskChange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepared(cls)
        cls.runs = {}
        for title, (settings, work, review) in TASKS.items():
            akconfig.write(cls.home, ["opus", "astra"], settings=settings)
            cls.fakes["claude"].behave(*work)
            cls.fakes["codex"].behave(*review)
            built, reviewed = len(cls.fakes["claude"].runs()), reviews(cls.fakes)
            task = taskfile.write(cls.home, cls.rig.path, title)
            done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
            run_dir, = [path for path in taskfile.runs(cls.home)
                        if path.name.endswith("-" + taskfile.slug(title))]
            cls.runs[title] = (done, json.loads((run_dir / "run.json").read_text()),
                               cls.fakes["claude"].runs()[built:],
                               reviews(cls.fakes) - reviewed)

    def blocked(self, title, lines, ceiling):
        done, state, turns, reviewed = self.runs[title]
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual((state["verdict"], reviewed), ("BLOCKED", 0))
        branch = f"ak/{taskfile.slug(title)}"
        self.assertEqual(state["error"],
                         f"The change on {branch} adds {lines} lines {TAIL} {ceiling}; split it")
        self.assertEqual([turn["role"] for turn in turns], ["executor"])
        self.assertIn(f"this change adds {lines} lines {TAIL} {ceiling}", turns[0]["hand_ins"][0]["err"])

    def test_a_lower_setting_blocks_a_change_under_ak_s_default_and_the_executor_is_told(self):
        self.blocked("Cut to 120", 150, 120)

    def test_no_setting_reads_300(self):
        self.blocked("Left at 300", 301, 300)

    def test_a_higher_setting_takes_the_executor_s_done_over_ak_s_default_and_reviews_it(self):
        done, state, turns, reviewed = self.runs["Raised to 500"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["verdict"], reviewed), ("PASS", 2))
        self.assertEqual([turn["role"] for turn in turns], ["executor", "fixer"])
        self.assertEqual(turns[0]["hand_ins"][0]["code"], 0, turns[0]["hand_ins"])


# The lines a seat builds itself are settings on the settings screen. [30 Oct 2026]
class SeatPullRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepared(cls)
        gh = GitHub(cls.home)
        Seat(cls.home, "acme", model="opus", cwd=cls.rig.path, alive=False, planned=True)
        cls.pulls = {}
        for branch, (settings, lines) in PULLS.items():
            akconfig.write(cls.home, ["opus", "astra"], settings=settings)
            cls.rig.branch(branch, {"contrib.txt": rows(lines)})
            url = gh.open_pr(cls.rig, branch, title=branch)
            before = reviews(cls.fakes)
            done = cls.home.ak("run", "--review-pr", url, "--no-merge", cwd=cls.rig.path,
                               env={"AGENTKIT_SESSION": "acme"}, timeout=300)
            cls.pulls[branch] = (done, url.rsplit("/", 1)[1], reviews(cls.fakes) - before)

    def refused(self, branch, lines, limit):
        done, number, reviewed = self.pulls[branch]
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn(f"PR #{number} adds {lines} lines (generated files and unchanged moves "
                      f"aside): too big for the seat, which builds at most {limit} added lines. "
                      "Write it as a task and launch it; a worker builds it", done.err)
        self.assertEqual(reviewed, 0)

    def test_a_lower_setting_refuses_a_pull_request_under_ak_s_default(self):
        self.refused("cut-to-20", 25, 20)

    def test_no_setting_reads_50(self):
        self.refused("left-at-50", 51, 50)

    def test_a_higher_setting_reviews_a_pull_request_over_ak_s_default(self):
        for branch in ("raised-to-100", "raised-to-500"):
            with self.subTest(branch=branch):
                done, _, reviewed = self.pulls[branch]
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(reviewed, 1)


if __name__ == "__main__":
    unittest.main()
