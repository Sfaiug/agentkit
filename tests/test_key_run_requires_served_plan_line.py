"""A seat's executor tasks must match open plan checks before ak starts a run or job."""

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

API = "test -f api.txt"
WEB = "test -f web.txt"
PAGE = "test -f page.txt"


class SeatLaunch(unittest.TestCase):
    planned = (API,)

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "acme")
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        self.fakes = fakeadapter.install(self.home, claude={**fakeadapter.WORK,
                                         "write": {"web.txt": "web\n"}}, codex="pass")
        self.seat = Seat(self.home, "fix-api", alive=False, cwd=self.rig.path, planned=self.planned,
                         record={"repo": str(self.rig.path), "reviewers": ["astra"]})
        self.web = taskfile.write(self.home, self.rig.path, "Add web", done_when=(WEB,))

    def ak(self, *args, seat=True):
        return self.home.ak(*args, cwd=self.rig.path, timeout=300,
                            env={"AGENTKIT_SESSION": self.seat.name if seat else None})


class RunRequiresServedPlanLine(SeatLaunch):
    def accepted(self, *args, seat=True):
        done = self.ak("run", *args, "--no-merge", seat=seat)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads((taskfile.only_run(self.home) / "run.json").read_text())

    def assertRefused(self, done, task):
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn(task.name, done.err)
        self.assertIn("ak plan add", done.err)
        self.assertEqual([fake.n for fake in self.fakes.values()], [0, 0])

    def plan_web(self):
        done = self.ak("plan", "add", "Web is ready", "--check", WEB)
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_adding_the_missing_line_allows_the_same_task_and_records_its_link(self):
        self.assertRefused(self.ak("run", self.web, "--no-merge"), self.web)
        self.assertEqual(taskfile.runs(self.home), [])
        self.plan_web()
        self.assertRegex(self.accepted(self.web)["plan_line"], r"^Web is ready · written ")

    def test_once_matches_the_bare_plan_check(self):
        self.plan_web()
        task = taskfile.write(self.home, self.rig.path, done_when=(WEB + "  # once",))
        self.assertRegex(self.accepted(task)["plan_line"], r"^Web is ready · written ")

    def test_an_unmatched_later_task_refuses_the_whole_job(self):
        api = taskfile.write(self.home, self.rig.path, "Add api", done_when=(API,))
        for flags in (("--in-order",), ("--parallel", "2")):
            with self.subTest(flags=flags):
                self.assertRefused(self.ak("run", api, self.web, *flags, "--bg"), self.web)
                self.assertEqual(taskfile.runs(self.home), [])
                self.assertEqual(list((self.home.path / ".agentkit/jobs").glob("*")), [])

    def test_an_ordered_job_keeps_its_line_after_the_first_merge_ticks_it(self):
        GitHub(self.home).grant(self.rig.slug, "WRITE")
        self.plan_web()
        self.assertEqual(self.ak("plan", "add", "Page is ready", "--check", PAGE).code, 0)
        page = taskfile.write(self.home, self.rig.path, "Add page",
                              done_when=(PAGE, "test -f links.txt"))
        self.fakes["claude"].behave({**fakeadapter.WORK, "write": {"web.txt": "web", "page.txt": "page"}},
                                   {**fakeadapter.WORK, "write": {"links.txt": "links"}})
        done = self.ak("run", self.web, page, "--in-order")
        self.assertEqual(done.code, 0, done.out + done.err)
        states = [json.loads((path / "run.json").read_text()) for path in taskfile.runs(self.home)]
        self.assertEqual(len(states), 2)
        for state in states:
            self.assertTrue(state["merged"])
            part = Path(state["task_file"]).stem.split("-")[-1].title()
            self.assertRegex(state["plan_line"], rf"^{part} is ready · written ")
        plan = (self.home.path / ".agentkit/state/plan-fix-api.md").read_text()
        self.assertIn("- [x] Page is ready", plan)

    def test_a_fourth_check_that_is_the_declared_suite_still_needs_a_match(self):
        task = taskfile.write(self.home, self.rig.path, "Add web", done_when=(
            WEB, "test -f page.txt", "test -f form.txt", "true"))
        api = taskfile.write(self.home, self.rig.path, "Add api", done_when=(API,))
        self.assertRefused(self.ak("run", api, task, "--in-order"), task)
        self.assertEqual(list((self.home.path / ".agentkit/jobs").glob("*")), [])
        self.assertRefused(self.ak("run", task), task)

    def test_review_pr_can_launch_with_any_open_line(self):
        gh = GitHub(self.home)
        self.rig.branch("docs", {"docs.txt": "docs\n"})
        url = gh.open_pr(self.rig, "docs", author="bravo")
        self.fakes["claude"].behave("pass")
        self.assertEqual(self.accepted("--review-pr", url)["review_pr"], url)

    def test_an_unmatched_task_can_launch_outside_a_seat(self):
        self.assertIsNone(self.accepted(self.web, seat=False).get("plan_line"))


if __name__ == "__main__":
    unittest.main()
