"""An active task holds its seat's open plan line until it ends."""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest

from fixtures import fakeadapter, taskfile
from test_key_run_requires_served_plan_line import PAGE, SeatLaunch

SHARED = "node --test test/all.test.mjs"


class OnePlanLinePerTask(SeatLaunch):
    planned = (SHARED, PAGE)

    def setUp(self):
        super().setUp()
        self.fakes["claude"].behave({**fakeadapter.WORK, "sh": "sleep 180"})
        self.a, self.b, self.page = [taskfile.write(self.home, self.rig.path, name, done_when=checks)
                                     for name, checks in (("Fix api", [SHARED]), ("Fix web", [SHARED]),
                                                          ("Add page", [SHARED, PAGE]))]

    def launch(self, *args):
        return self.ak("run", *args, "--bg")

    def refused(self, done, path, check=SHARED):
        self.assertEqual(done.code, 2, done.out + done.err)
        for words in (path.name, check + " · written", "ak plan add", "## Done when"):
            self.assertIn(words, done.err)

    def test_job_refuses_before_creating_any_receipts(self):
        for flags in (("--in-order",), ("--parallel", "2")):
            self.refused(self.launch(self.a, self.b, *flags), self.b)
            self.assertEqual(list((self.home.path / ".agentkit/jobs").glob("*")), [])
            self.assertEqual(taskfile.runs(self.home), [])

    def test_queued_job_task_holds_its_own_line(self):
        done = self.launch(self.a, self.page, "--in-order")
        self.assertEqual(done.code, 0, done.out + done.err)
        page = taskfile.write(self.home, self.rig.path, "Publish page", done_when=(PAGE,))
        self.refused(self.launch(page), page, PAGE)

    def test_concurrent_launches_claim_once_and_release_on_stop(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.launch, (self.a, self.b)))
        self.assertEqual(sorted(r.code for r in results), [0, 2], results)
        loser = next(path for path, r in zip((self.a, self.b), results) if r.code)
        self.refused(next(r for r in results if r.code), loser)
        first = taskfile.only_run(self.home)
        done = self.launch(self.page)
        self.assertEqual(done.code, 0, done.out + done.err)
        second, = set(taskfile.runs(self.home)) - {first}
        self.assertTrue(json.loads((second / "run.json").read_text())["plan_line"].startswith(PAGE))
        done = self.ak("run", "stop", first.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        done = self.launch(loser)
        self.assertEqual(done.code, 0, done.out + done.err)
        replacement, = set(taskfile.runs(self.home)) - {first, second}
        self.assertTrue(json.loads((replacement / "run.json").read_text())["plan_line"].startswith(SHARED))


if __name__ == "__main__":
    unittest.main()
