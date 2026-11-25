"""`ak models --json` counts the tasks of the last 30 days by the team that did them (`runs`): a
task is a run of kind `task` judged in the window with every later run of its change, stopped
or running too, of the team of its first run (the run its change is named for, whatever start a
relaunch ties with), its orchestrator, executor and reviewer each a model at an effort (the
reviewer's its first review's).  Per team: its tasks, those merged on their first run, those
merged on any, and the hours every run of them spent.  A follow-up, a seat's own pull request and
a task whose first run ended outside the window, or recorded no end, count nowhere, nor do its
relaunches.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
runs and their reviews written into the Home's history.db; judged by the output and exit code.
Fails against /bin/false.
"""

import json
import sqlite3
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, NOW, boards

DAY = 86400
# Each run: an hour of build, half of review, a quarter of checks and an hour waiting,
# a part of it in each of the four waits
RUN = {"run_id": "", "repo": "acme", "kind": "task", "change": None,
       "orchestrator": "nova", "orchestrator_effort": "high", "executor": "bolt",
       "executor_effort": "max", "reviewer": "crux", "final_state": "pass", "verdict": "PASS",
       "rounds_used": 1, "changed_lines": 1, "started_at": 0, "finished_at": 0,
       "executor_seconds": 3600, "reviewer_seconds": 1800, "done_when_seconds": 900,
       "slot_wait_seconds": 360, "suite_wait_seconds": 720, "merge_wait_seconds": 1080,
       "lander_wait_seconds": 1440, "first_review_lines": None}
FAILED = {"final_state": "fail", "verdict": "FAIL", "changed_lines": None}
STOPPED = {"final_state": "stopped", "verdict": None, "changed_lines": None}
RUNNING = {**STOPPED, "final_state": "running", "finished_at": None}


def run(run_id, days_ago, **fields):
    return {**RUN, "run_id": run_id, "started_at": NOW - days_ago * DAY - 600,
            "finished_at": NOW - days_ago * DAY, **fields}


RUNS = [
    run("fix-api", 5),                                  # merged on its first run
    run("write-cache", 4, **FAILED),                    # failed, merged launched again from its
    run("finish-cache", 3, change="write-cache", executor="crux",   # branch by another, started
        started_at=NOW - 4 * DAY - 600),                # when it was
    run("fix-docs", 2, **FAILED),                       # failed
    run("fix-login", 1, executor_effort="low", **FAILED),       # team B's, failed, launched again
    run("fix-login-again", 0.5, change="fix-login", **STOPPED),     # and stopped, and again now
    run("fix-login-now", 0.25, change="fix-login", **RUNNING),
    run("fix-api-again", 1, kind="follow-up"),          # none is a task
    run("acme-pr", 1, kind="seat PR", change="acme/acme#7"),
    run("fix-old", 31),                                 # ended before the window, and so its
    run("fix-old-again", 1, change="fix-old"),          # relaunch
    run("fix-soon", -1 / 24),                           # ends after the window, an hour on
    run("fix-undated", 2, finished_at=None),            # recorded no end, and so its relaunch
    run("fix-undated-again", 1, change="fix-undated"),
]
# the effort of each first run's first review; fix-api's second round is at another
REVIEWS = [("fix-api", 1, "medium"), ("fix-api", 2, "high"), ("write-cache", 1, "medium"),
           ("fix-docs", 1, "medium"), ("fix-login", 1, "medium"), ("fix-old", 1, "medium"),
           ("fix-soon", 1, "medium"), ("fix-undated", 1, "medium")]


def history(home, runs, reviews):
    """The Home's history.db holding `runs` and a review per (run_id, round, effort) of
    `reviews`."""
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    with connection:
        connection.execute(f"CREATE TABLE runs ({', '.join(RUN)})")
        connection.executemany(f"INSERT INTO runs VALUES ({', '.join('?' * len(RUN))})",
                               [tuple(row.values()) for row in runs])
        connection.execute("CREATE TABLE reviews (run_id, review_id, harness, model, "
                           "blocking, followup, note, round, verdict, effort)")
        connection.executemany(
            "INSERT INTO reviews VALUES (?, ?, 'codex', 'crux-2', 0, 0, 0, ?, 'PASS', ?)",
            [(run_id, f"{run_id}-{round}", round, effort) for run_id, round, effort in reviews])
    connection.close()


def team(executor_effort, tasks, first_run, live, runs):
    return {"orchestrator": {"name": "nova", "effort": "high"},
            "executor": {"name": "bolt", "effort": executor_effort},
            "reviewer": {"name": "crux", "effort": "medium"},
            "tasks": tasks, "first_run": first_run, "live": live,
            "hours": {"build": runs, "review": runs / 2, "checks": runs / 4, "waiting": runs}}


class ModelsJsonCountsTasksByTeam(unittest.TestCase):
    def test_each_team_s_tasks_first_run_live_and_hours(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")
            akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5",
                                          "effort": "low"}})
            home.write(".agentkit/state/boards.json", boards())
            history(home, RUNS, REVIEWS)
            done = home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.err)
        runs = json.loads(done.out)["runs"]
        self.assertEqual(runs["until"] - runs["since"], 30 * DAY)
        self.assertTrue(NOW <= runs["until"] <= time.time())
        self.assertCountEqual(runs["teams"], [team("max", 3, 1, 2, 4.0), team("low", 1, 0, 0, 3.0)])


if __name__ == "__main__":
    unittest.main()
