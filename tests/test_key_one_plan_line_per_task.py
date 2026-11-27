"""An active task holds its seat's open plan line until it ends."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import unittest

from fixtures import fakeadapter, taskfile
from test_key_run_requires_served_plan_line import PAGE, WEB, SeatLaunch

SHARED = "node --test test/all.test.mjs"


class OnePlanLinePerTask(SeatLaunch):
    planned = (SHARED, WEB, PAGE)

    def test_tasks_hold_distinct_lines_until_they_end(self):
        task = partial(taskfile.write, self.home, self.rig.path)
        launch = partial(self.ak, "run", "--bg")

        def refused(done, path, line=SHARED):
            self.assertEqual(done.code, 2, done.out + done.err)
            for words in (path.name, line + " · written", "ak plan add", "## Done when"):
                self.assertIn(words, done.err)

        self.fakes["claude"].behave({**fakeadapter.WORK, "sh": "sleep 180"})
        api, ui = (task(name, done_when=(SHARED,)) for name in ("Fix API", "Fix UI"))
        jobs = self.home.path / ".agentkit/jobs"
        for flags in (("--in-order",), ("--parallel", "2")):
            refused(launch(api, ui, *flags), ui)
            self.assertEqual([*jobs.glob("*"), *taskfile.runs(self.home)], [])

        with ThreadPoolExecutor(2) as pool:
            attempts = list(zip(pool.map(launch, (api, ui)), (api, ui)))
        winner, loser = sorted(attempts, key=lambda attempt: attempt[0].code)
        self.assertEqual(winner[0].code, 0, winner[0])
        refused(*loser)
        first = taskfile.only_run(self.home)
        done = launch(task("Publish page", done_when=(SHARED, PAGE)), self.web, "--in-order")
        self.assertEqual(done.code, 0, done.out + done.err)
        receipt, = jobs.glob("*/job.json")
        lines = [t["plan_line"].split(" · written ")[0] for t in json.loads(receipt.read_text())["tasks"]]
        self.assertEqual(lines, [PAGE, WEB])
        refused(launch(self.web), self.web, WEB)
        self.assertEqual(self.ak("run", "stop", first.name).code, 0)
        self.assertEqual(launch(loser[1]).code, 0)


if __name__ == "__main__":
    unittest.main()
