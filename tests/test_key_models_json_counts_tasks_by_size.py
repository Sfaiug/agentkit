"""`ak models --json` counts the tasks of the last 30 days by their size (`runs`' `sizes`), the
same tasks it counts by team (tests/test_key_models_json_counts_tasks_by_team.py): a task's size
is the most lines a first review of one of its runs read, its row the least whole hundred no less
than that, 100 for 0; one no run of which kept a size is in no row.  Per row, smallest first, and
none for a hundred with no task: its tasks, those any of whose runs merged, the sizes of those
summed, and the hours every run of them spent.  A follow-up counts in no row.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
runs written into the Home's history.db; judged by the output and exit code.  Fails against
/bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from test_key_models_json_counts_tasks_by_team import FAILED, STOPPED, counted, history, run

# Each run as RUN in the key of the tasks by team: merged, an hour of build, half of review, a
# quarter of checks and an hour waiting
RUNS = [
    run("fix-api", 5, first_review_lines=0),
    run("fix-docs", 5, first_review_lines=100),
    run("fix-menu", 4, first_review_lines=101),
    run("write-cache", 4, first_review_lines=120, **FAILED),   # failed, and launched again: its
    run("redo-cache", 3, change="write-cache", first_review_lines=250, **STOPPED),  # most kept
    run("finish-cache", 2, change="write-cache", first_review_lines=180),
    run("fix-login", 2, first_review_lines=450, **FAILED),     # failed
    run("fix-ui", 1),                                          # no run of it kept a size
    run("fix-ui-again", 1, kind="follow-up", first_review_lines=380),
]


def size(upto, tasks, live, lines_live, runs):
    return {"upto": upto, "tasks": tasks, "live": live, "lines_live": lines_live,
            "hours": {"build": runs, "review": runs / 2, "checks": runs / 4, "waiting": runs}}


class ModelsJsonCountsTasksBySize(unittest.TestCase):
    def test_each_hundred_s_tasks_live_lines_live_and_hours(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")
            akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5",
                                          "effort": "low"}})
            home.write(".agentkit/state/boards.json", boards())
            history(home, RUNS, [])
            done = home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.err)
        runs = json.loads(done.out)["runs"]
        # fix-ui with the rest, its follow-up nowhere
        self.assertEqual([team["tasks"] for team in runs["teams"]], [6])
        self.assertEqual(runs["sizes"], [size(100, 2, 2, 100, 2.0), size(200, 1, 1, 101, 1.0),
                                         size(300, 1, 1, 250, 3.0), size(500, 1, 0, 0, 1.0)])

    def test_a_size_past_float_precision_lands_in_its_own_hundred(self):
        large = 2 * 10**18
        done = counted([run("fix-at", 2, first_review_lines=large),
                        run("fix-over", 1, first_review_lines=large + 1)], [])
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["sizes"], [
            size(large, 1, 1, large, 1.0),
            size(large + 100, 1, 1, large + 1, 1.0)])


if __name__ == "__main__":
    unittest.main()
