"""`ak models --json` counts the tasks of the last 30 days by the review rounds they went through
(`runs`' `rounds`), the same tasks it counts by team and by first review's issues
(tests/test_key_models_json_counts_tasks_by_team.py,
tests/test_key_models_json_counts_tasks_by_first_issues.py): a task's number is the highest
round among the reviews of a round over every run of it, a relaunch's too; a task with no such
review is in no row.  Per row, fewest rounds first, and none for a number with no task: what a
row of `runs.first_issues` holds of its tasks, its `usage` as that row holds it.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
runs and their reviews written into the Home's history.db; judged by the output and exit code.
Fails against /bin/false.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_counts_tasks_by_team import FAILED, counted, history, run
from test_key_models_json_week_meters import WeekMeters
import test_key_models_json_run_usage as run_usage
from test_key_models_json_run_usage import EMPTY, TABLES


def row(rounds, tasks, first_run, live, runs, usage=EMPTY):
    return {"rounds": rounds, "tasks": tasks, "first_run": first_run, "live": live,
            "hours": {"build": runs, "review": runs / 2, "checks": runs / 4, "waiting": runs},
            "usage": usage}


class ModelsJsonCountsTasksByRounds(unittest.TestCase):
    def test_tasks_of_one_three_and_three_rounds_give_two_rows(self):
        runs = [run("fix-api", 5), run("fix-docs", 4), run("fix-menu", 3, **FAILED)]
        reviews = [
            ("fix-api", 1, "medium", "PASS", 0),
            ("fix-docs", 1, "medium", "FAIL", 2),
            ("fix-docs", 2, "medium", "FAIL", 1),
            ("fix-docs", 3, "medium", "PASS", 0),
            ("fix-menu", 1, "medium", "FAIL", 2),
            ("fix-menu", 2, "medium", "FAIL", 2),
            ("fix-menu", 3, "medium", "FAIL", 1),
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["rounds"], [
            row(1, 1, 1, 1, 1.0),
            row(3, 2, 1, 1, 2.0)])

    def test_a_relaunch_that_passed_in_round_five_is_in_row_five_live_not_first_run(self):
        runs = [run("write-cache", 4, **FAILED),
                run("finish-cache", 2, change="write-cache")]
        reviews = [
            ("write-cache", 1, "medium", "FAIL", 3),
            ("write-cache", 2, "medium", "FAIL", 2),
            ("write-cache", 3, "medium", "FAIL", 2),
            ("finish-cache", 4, "medium", "FAIL", 1),
            ("finish-cache", 5, "medium", "PASS", 0),
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["rounds"], [row(5, 1, 0, 1, 2.0)])

    def test_a_task_with_no_review_of_a_round_is_in_no_row(self):
        runs = [run("fix-api", 5), run("fix-unreviewed", 4), run("fix-legacy", 3)]
        reviews = [
            ("fix-api", 1, "medium", "PASS", 0),
            ("fix-legacy", None, None, "FAIL", 4),       # no round: `reviews` counts it not
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        found = json.loads(done.out)["runs"]
        self.assertEqual(sum(team["tasks"] for team in found["teams"]), 3)
        self.assertEqual(found["rounds"], [row(1, 1, 1, 1, 1.0)])


class ModelsJsonRoundsUsage(WeekMeters):
    seat, turn = run_usage.ModelsJsonRunUsage.seat, run_usage.ModelsJsonRunUsage.turn

    def test_each_row_s_usage_sums_its_tasks_builds_reviews_and_orchestrator_share(self):
        # acme/Max: 100 pts/M for anvil-1; nova at high took 8 points and 4,000 unrated tokens
        # over its four tasks, fix-text's share in no row
        self.read(50, 10)
        self.seat(45, 80_000, orchestrator="nova", effort="high")
        self.read(40, 18)
        self.seat(35, 4_000, model="anvil-9", orchestrator="nova", effort="high")
        self.turn(35, (100_000, 0, 0, 0), run_id="fix-api", role="executor")
        self.turn(35, (20_000, 0, 0, 0), run_id="fix-api", role="reviewer")
        self.turn(35, (30_000, 0, 0, 0), run_id="write-cache", role="executor")
        self.turn(35, (30_000, 0, 0, 0), run_id="write-cache", role="reviewer")
        self.turn(35, (10_000, 0, 0, 0), run_id="finish-cache", role="executor")
        self.turn(35, (2_000, 0, 0, 0), model="anvil-9", run_id="finish-cache", role="reviewer")
        self.turn(35, (60_000, 0, 0, 0), run_id="fix-menu", role="executor")
        self.turn(35, (50_000, 0, 0, 0), run_id="fix-menu", role="reviewer")
        self.turn(35, (50_000, 0, 0, 0), run_id="fix-text", role="executor")
        history(self.home, [
            run("fix-api", 5),
            run("write-cache", 4, **FAILED),
            run("finish-cache", 3, change="write-cache"),
            run("fix-menu", 3),
            run("fix-text", 2),
        ], [
            ("fix-api", 1, "medium", "PASS", 0),
            ("write-cache", 1, "medium", "FAIL", 2),
            ("finish-cache", 2, "medium", "PASS", 0),
            ("fix-menu", 1, "medium", "FAIL", 2),
            ("fix-menu", 2, "medium", "PASS", 0),
        ])
        self.assertEqual(self.answer(TABLES)["runs"]["rounds"], [
            row(1, 1, 1, 1, 1.0, {
                "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
                "reviewer": {"points": {"acme": {"Max": 2}}, "unrated": 0},
                "orchestrator": {"points": {"acme": {"Max": 2}}, "unrated": 1_000}}),
            row(2, 2, 1, 2, 3.0, {
                "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
                "reviewer": {"points": {"acme": {"Max": 8}}, "unrated": 2_000},
                "orchestrator": {"points": {"acme": {"Max": 4}}, "unrated": 2_000}})])


if __name__ == "__main__":
    unittest.main()
