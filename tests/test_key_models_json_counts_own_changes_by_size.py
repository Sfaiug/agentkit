"""`ak models --json` counts the seats' own changes of the last 30 days by their size (`runs`'
`own_sizes`): an own change is a run of kind `seat PR` judged in the window with every later run
of its change, stopped or running too; its size is the most lines a first review of one of its
runs read, its row the least multiple of 25 no less than that, 25 for 0; one no run of which kept
a size is in no row.  Per row, smallest first, and none for a 25 with no own change: its changes,
those any of whose runs merged (`live`), the sizes of those summed (`lines_live`), the hours every
run of them spent, and the usage every run of them took in fixes (`executor`) and reviews
(`reviewer`), `orchestrator` holding nothing.  Tasks and other kinds are in no row, and an own
change is in no count of tasks.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
runs written into the Home's history.db; judged by the output and exit code.  Fails against
/bin/false.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_counts_tasks_by_size import size
from test_key_models_json_counts_tasks_by_team import FAILED, STOPPED, counted, history, run, took
from test_key_models_json_week_meters import WeekMeters
import test_key_models_json_run_usage as run_usage
from test_key_models_json_run_usage import EMPTY, TABLES


def own(run_id, days_ago, change, **fields):
    return run(run_id, days_ago, kind="seat PR", change=change, **fields)


def row(upto, changes, live, lines_live, runs, usage=EMPTY):
    return {"upto": upto, "changes": changes, "live": live, "lines_live": lines_live,
            "hours": {"build": runs, "review": runs / 2, "checks": runs / 4, "waiting": runs},
            "usage": usage}


class ModelsJsonCountsOwnChangesBySize(unittest.TestCase):
    def test_own_changes_of_10_20_and_40_lines_give_two_rows(self):
        done = counted([
            own("pr-1", 5, "acme/api#1", first_review_lines=10),
            own("pr-2", 4, "acme/api#2", first_review_lines=20),
            own("pr-3", 3, "acme/api#3", first_review_lines=40, **FAILED),
        ], [("pr-1", 1, "medium", "PASS", 0)])
        self.assertEqual(done.code, 0, done.err)
        found = json.loads(done.out)["runs"]
        self.assertEqual(found["own_sizes"], [row(25, 2, 2, 30, 2.0), row(50, 1, 0, 0, 1.0)])
        self.assertEqual((found["teams"], found["sizes"], found["first_issues"], found["rounds"]),
                         ([], [], [], []))

    def test_a_change_failing_first_and_merging_later_counts_once_live(self):
        done = counted([
            own("pr-cache-1", 4, "acme/api#4", first_review_lines=15, **FAILED),
            own("pr-cache-2", 3, "acme/api#4", first_review_lines=30, **STOPPED),
            own("pr-cache-3", 2, "acme/api#4", first_review_lines=20),
        ], [])
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["own_sizes"], [row(50, 1, 1, 30, 3.0)])

    def test_a_task_and_an_unsized_own_change_are_in_no_row(self):
        done = counted([
            own("pr-1", 5, "acme/api#1", first_review_lines=25),
            own("pr-0", 4.5, "acme/api#2", first_review_lines=0),
            run("fix-api", 4, first_review_lines=10),
            own("pr-unsized", 3, "acme/api#3"),
            own("pr-old", 31, "acme/api#4", first_review_lines=10),
            own("pr-old-again", 1, "acme/api#4", first_review_lines=10),
            run("other-pr", 1, kind="PR", change="acme/api#9", first_review_lines=10),
        ], [])
        self.assertEqual(done.code, 0, done.err)
        found = json.loads(done.out)["runs"]
        self.assertEqual(found["own_sizes"], [row(25, 2, 2, 25, 2.0)])
        self.assertEqual(found["sizes"], [size(100, 1, 1, 10, 1.0)])
        self.assertEqual([team["tasks"] for team in found["teams"]], [1])


class ModelsJsonOwnSizeUsage(WeekMeters):
    seat, turn = run_usage.ModelsJsonRunUsage.seat, run_usage.ModelsJsonRunUsage.turn

    def test_each_row_s_usage_sums_its_changes_fixes_and_reviews(self):
        # acme/Max: 100 pts/M for anvil-1; nova's seat stays on its tasks, never own_sizes
        self.read(50, 10)
        self.seat(45, 100_000, orchestrator="nova", effort="high")
        self.read(40, 20)
        self.turn(35, (100_000, 0, 0, 0), run_id="pr-1", role="executor")
        self.turn(35, (20_000, 0, 0, 0), run_id="pr-1", role="reviewer")
        self.turn(35, (30_000, 0, 0, 0), run_id="pr-cache-1", role="executor")
        self.turn(35, (10_000, 0, 0, 0), run_id="pr-cache-2", role="executor")
        self.turn(35, (2_000, 0, 0, 0), model="anvil-9", run_id="pr-cache-2", role="reviewer")
        self.turn(35, (50_000, 0, 0, 0), run_id="pr-unsized", role="executor")
        history(self.home, [
            own("pr-1", 5, "acme/api#1", first_review_lines=10),
            own("pr-cache-1", 4, "acme/api#4", first_review_lines=15, **FAILED),
            own("pr-cache-2", 3, "acme/api#4", first_review_lines=30),
            own("pr-unsized", 2, "acme/api#3"),
            run("fix-api", 2, first_review_lines=10),
        ], [])
        found = self.answer(TABLES)["runs"]
        self.assertEqual(found["own_sizes"], [
            row(25, 1, 1, 10, 1.0, {**EMPTY,
                                    "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
                                    "reviewer": {"points": {"acme": {"Max": 2}}, "unrated": 0}}),
            row(50, 1, 1, 30, 2.0, {**EMPTY,
                                    "executor": {"points": {"acme": {"Max": 4}}, "unrated": 0},
                                    "reviewer": {"points": {}, "unrated": 2_000}})])
        # fix-api keeps all of nova's seat share; pr-unsized stays in runs.usage alone
        self.assertEqual(found["sizes"], [size(100, 1, 1, 10, 1.0, took({"acme": {"Max": 10}}))])
        self.assertEqual([team["usage"] for team in found["teams"]],
                         [took({"acme": {"Max": 10}})])
        self.assertEqual(found["usage"], {
            "executor": {"points": {"acme": {"Max": 19}}, "unrated": 0},
            "reviewer": {"points": {"acme": {"Max": 2}}, "unrated": 2_000},
            "orchestrator": {"points": {"acme": {"Max": 10}}, "unrated": 0}})


if __name__ == "__main__":
    unittest.main()
