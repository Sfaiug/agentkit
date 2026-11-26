"""`ak models --json` counts the tasks of the last 30 days by the blocking issues their first
review found (`runs`' `first_issues`), the same tasks it counts by team and by size
(tests/test_key_models_json_counts_tasks_by_team.py,
tests/test_key_models_json_counts_tasks_by_size.py): a task's number is the `blocking` of its
first run's first review (the review `first_pass` reads); a task with no such review, or whose
`blocking` is no whole number of zero or more, is in no row.  Per row, fewest issues first, and
none for a number with no task: its tasks, those whose first run merged (`first_run`), those any
of whose runs merged (`live`), the hours every run of them spent, and their `usage` as a row of
`runs.sizes` holds it.  A follow-up counts in no row.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
runs and their reviews written into the Home's history.db; judged by the output and exit code.
Fails against /bin/false.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_counts_tasks_by_team import FAILED, STOPPED, counted, history, run
from test_key_models_json_week_meters import WeekMeters
import test_key_models_json_run_usage as run_usage
from test_key_models_json_run_usage import EMPTY, TABLES


def row(issues, tasks, first_run, live, runs, usage=EMPTY):
    return {"issues": issues, "tasks": tasks, "first_run": first_run, "live": live,
            "hours": {"build": runs, "review": runs / 2, "checks": runs / 4, "waiting": runs},
            "usage": usage}


class ModelsJsonCountsTasksByFirstIssues(unittest.TestCase):
    def test_tasks_by_their_first_review_s_issues_give_one_row_per_number(self):
        runs = [
            run("fix-api", 5),
            run("fix-docs", 4),
            run("fix-menu", 3, **FAILED),
            run("fix-api-again", 1, kind="follow-up"),
        ]
        reviews = [
            ("fix-api", 1, "medium", "PASS", 0),
            ("fix-docs", 1, "medium", "FAIL", 2),
            ("fix-docs", 2, "medium", "PASS", 0),        # round 2 never replaces round 1
            ("fix-menu", 1, "medium", "FAIL", 2),
            ("fix-api-again", 1, "medium", "FAIL", 5),   # follow-up in no row
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["first_issues"], [
            row(0, 1, 1, 1, 1.0),
            row(2, 2, 1, 1, 2.0)])

    def test_a_relaunch_that_went_live_counts_live_and_not_first_run(self):
        runs = [
            run("write-cache", 4, **FAILED),
            run("redo-cache", 3, change="write-cache", **STOPPED),
            run("finish-cache", 2, change="write-cache"),
        ]
        reviews = [
            ("write-cache", 1, "medium", "FAIL", 3),
            ("redo-cache", 1, "medium", "FAIL", 1),
            ("finish-cache", 1, "medium", "PASS", 0),
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["first_issues"], [row(3, 1, 0, 1, 3.0)])

    def test_tasks_with_no_first_review_or_non_whole_blocking_are_in_no_row(self):
        runs = [
            run("fix-api", 5),
            run("fix-unreviewed", 4),
            run("fix-legacy", 3),
            run("fix-text", 2),
            run("fix-neg", 1),
        ]
        reviews = [
            ("fix-api", 1, "medium", "PASS", 0),
            ("fix-legacy", None, None, "FAIL", 4),       # no round: not a first review
            ("fix-text", 1, "medium", "FAIL", "two"),
            ("fix-text", 2, "medium", "PASS", 0),
            ("fix-neg", 1, "medium", "FAIL", -1),
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        found = json.loads(done.out)["runs"]
        self.assertEqual(sum(team["tasks"] for team in found["teams"]), 5)
        self.assertEqual(found["first_issues"], [row(0, 1, 1, 1, 1.0)])


class ModelsJsonFirstIssuesUsage(WeekMeters):
    seat, turn = run_usage.ModelsJsonRunUsage.seat, run_usage.ModelsJsonRunUsage.turn

    def test_each_row_s_usage_sums_its_tasks_builds_reviews_and_orchestrator_share(self):
        # acme/Max: 100 pts/M for anvil-1; nova at high took 8 points and 4,000 unrated tokens
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
            ("fix-menu", 1, "medium", "FAIL", 2),
            ("fix-text", 1, "medium", "FAIL", "two"),
        ])
        found = self.answer(TABLES)["runs"]
        self.assertEqual(found["first_issues"], [
            row(0, 1, 1, 1, 1.0, {
                "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
                "reviewer": {"points": {"acme": {"Max": 2}}, "unrated": 0},
                "orchestrator": {"points": {"acme": {"Max": 2}}, "unrated": 1_000}}),
            row(2, 2, 1, 2, 3.0, {
                "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
                "reviewer": {"points": {"acme": {"Max": 8}}, "unrated": 2_000},
                "orchestrator": {"points": {"acme": {"Max": 4}}, "unrated": 2_000}})])
        # fix-text's build and its share of nova's seats stay in its team alone
        self.assertEqual([team["usage"] for team in found["teams"]], [{
            "executor": {"points": {"acme": {"Max": 25}}, "unrated": 0},
            "reviewer": {"points": {"acme": {"Max": 10}}, "unrated": 2_000},
            "orchestrator": {"points": {"acme": {"Max": 8}}, "unrated": 4_000}}])


if __name__ == "__main__":
    unittest.main()
