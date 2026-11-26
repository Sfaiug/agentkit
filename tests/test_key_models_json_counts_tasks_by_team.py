"""`ak models --json` counts the tasks of the last 30 days by the team that did them (`runs`): a
task is a run of kind `task` judged in the window with every later run of its change, stopped
or running too, of the team of its first run (the run its change is named for, whatever start a
relaunch ties with), its orchestrator, executor and reviewer each a model at an effort (the
reviewer's its first review's).  Per team: its tasks, those merged on their first run, those
merged on any, those whose first run's first review (round 1) passed, the reviews of a round
over every run of them, their blocking issues summed, their answered disputes and those the
reviewer took back (`conceded` or `dropped`), the hours every run of them spent, the usage
every run of them took by role (as `runs.usage`, tests/test_key_models_json_run_usage.py), and,
as `orchestrator`, of the `runs.seats` entry of its orchestrator's name and effort (of no name
where it has no effort, whatever name it holds) its tasks over those of every team of that entry,
`unrated` rounded half to even; an entry no team matches is in no team.
A follow-up, a seat's own pull request and a task whose first run ended outside the window, or
recorded no end, count nowhere, nor do its relaunches.

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
from test_key_models_json_week_meters import WeekMeters
import test_key_models_json_run_usage as run_usage
from test_key_models_json_run_usage import EMPTY, TABLES

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


def history(home, runs, reviews, findings=None):
    """The Home's history.db holding `runs`, a review per (run_id, round, effort[, verdict,
    blocking]) of `reviews`, and, where given, a finding per (run_id, outcome) of `findings`."""
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    with connection:
        connection.execute(f"CREATE TABLE runs ({', '.join(RUN)})")
        connection.executemany(f"INSERT INTO runs VALUES ({', '.join('?' * len(RUN))})",
                               [tuple(row.values()) for row in runs])
        connection.execute("CREATE TABLE reviews (run_id, review_id, harness, model, "
                           "blocking, followup, note, round, verdict, effort)")
        rows = []
        for index, (run_id, round, effort, *rest) in enumerate(reviews):
            verdict = rest[0] if rest else "PASS"
            blocking = rest[1] if len(rest) > 1 else 0
            rows.append((run_id, f"{run_id}-{index}", blocking, round, verdict, effort))
        connection.executemany(
            "INSERT INTO reviews VALUES (?, ?, 'codex', 'crux-2', ?, 0, 0, ?, ?, ?)", rows)
        if findings is not None:
            connection.execute("CREATE TABLE findings (run_id, review_id, round, path, line, "
                               "handed, kind, proof, commit_exit, base_exit, replayed, reason, "
                               "outcome, at)")
            connection.executemany(
                "INSERT INTO findings VALUES (?, 'r-1', 1, 'a.py', 1, ?, ?, 'p', "
                "NULL, NULL, NULL, NULL, ?, ?)",
                [(run_id, "finding" if outcome is None else "dispute",
                  "finding" if outcome is None else "dispute", outcome, NOW - DAY)
                 for run_id, outcome in findings])
    connection.close()


def team(executor_effort, tasks, first_run, live, runs, first_pass, reviews, issues=0,
         disputed=0, taken_back=0, reviewer_effort="medium", usage=EMPTY, orchestrator="nova",
         orchestrator_effort="high"):
    return {"orchestrator": {"name": orchestrator, "effort": orchestrator_effort},
            "executor": {"name": "bolt", "effort": executor_effort},
            "reviewer": {"name": "crux", "effort": reviewer_effort},
            "tasks": tasks, "first_run": first_run, "live": live,
            "first_pass": first_pass, "reviews": reviews, "issues": issues,
            "disputed": disputed, "taken_back": taken_back,
            "hours": {"build": runs, "review": runs / 2, "checks": runs / 4, "waiting": runs},
            "usage": usage}


def counted(runs, reviews, findings=None, *, readonly=False):
    with Home() as home:
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5",
                                      "effort": "low"}})
        home.write(".agentkit/state/boards.json", boards())
        history(home, runs, reviews, findings)
        if readonly:
            (home.path / ".agentkit/history.db").chmod(0o444)
        return home.ak("models", "--json", env=ENV)


class ModelsJsonCountsTasksByTeam(unittest.TestCase):
    def test_each_team_s_tasks_first_run_live_and_hours(self):
        done = counted(RUNS, REVIEWS)
        self.assertEqual(done.code, 0, done.err)
        runs = json.loads(done.out)["runs"]
        self.assertEqual(runs["until"] - runs["since"], 30 * DAY)
        self.assertTrue(NOW <= runs["until"] <= time.time())
        self.assertCountEqual(runs["teams"], [
            team("max", 3, 1, 2, 4.0, 3, 4), team("low", 1, 0, 0, 3.0, 1, 1)])

    def test_each_team_s_first_pass_reviews_and_issues(self):
        runs = [
            run("fix-api", 5),
            run("fix-docs", 4),
            run("fix-legacy", 3.5),
            run("write-cache", 3, executor_effort="low", **FAILED),
            run("finish-cache", 2, change="write-cache", executor="crux"),
            run("fix-api-again", 1, kind="follow-up"),
        ]
        reviews = [
            ("fix-api", 1, "medium", "PASS", 0),           # first review passed
            ("fix-docs", 1, "medium", "FAIL", 2),          # first failed, second passed; text
            ("fix-docs", 2, "high", "PASS", "two"),        # blocking counts no issues
            ("fix-legacy", None, None, "FAIL", 5),         # no round: counts nothing, keeps
            ("fix-legacy", 1, "high", "PASS", 0),          # unrecorded reviewer effort
            ("write-cache", 1, "medium", "FAIL", 3),       # relaunch's reviews join its team
            ("finish-cache", 1, "high", "FAIL", 1),
            ("finish-cache", 2, "high", "PASS", 0),
            ("fix-api-again", 1, "medium", "PASS", 4),     # follow-up's reviews in no team
        ]
        done = counted(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        self.assertCountEqual(json.loads(done.out)["runs"]["teams"], [
            team("max", 2, 2, 2, 2.0, 1, 3, 2),
            team("max", 1, 1, 1, 1.0, 1, 1, 0, reviewer_effort=None),
            team("low", 1, 0, 1, 2.0, 0, 3, 4)])

    def test_each_team_s_disputed_and_taken_back_issues(self):
        runs = [run("fix-api", 3)]
        reviews = [("fix-api", 1, "medium", "FAIL", 4), ("fix-api", 2, "medium", "PASS", 0)]
        findings = [
            ("fix-api", "upheld"), ("fix-api", "conceded"), ("fix-api", "dropped"),
            ("fix-api", None),              # a finding with no outcome counts nothing
            ("fix-api", 1),                 # non-text outcome counts nothing
        ]
        done = counted(runs, reviews, findings)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["teams"], [
            team("max", 1, 1, 1, 1.0, 0, 2, 4, disputed=3, taken_back=2)])

    def test_a_relaunch_s_disputes_join_its_task_s_team_and_a_follow_up_s_are_in_no_team(self):
        runs = [
            run("write-cache", 3, executor_effort="low", **FAILED),
            run("finish-cache", 2, change="write-cache", executor="crux"),
            run("fix-api-again", 1, kind="follow-up"),
        ]
        reviews = [
            ("write-cache", 1, "medium", "FAIL", 2),
            ("finish-cache", 1, "high", "FAIL", 1), ("finish-cache", 2, "high", "PASS", 0),
            ("fix-api-again", 1, "medium", "PASS", 1),
        ]
        findings = [
            ("write-cache", "upheld"),
            ("finish-cache", "conceded"), ("finish-cache", "dropped"),
            ("fix-api-again", "conceded"),
        ]
        done = counted(runs, reviews, findings)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["teams"], [
            team("low", 1, 0, 1, 2.0, 0, 3, 3, disputed=3, taken_back=2)])

    def test_a_history_with_no_findings_table_gives_zero_disputes(self):
        runs = [run("fix-api", 3)]
        reviews = [("fix-api", 1, "medium", "FAIL", 2), ("fix-api", 2, "medium", "PASS", 0)]
        done = counted(runs, reviews, readonly=True)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out)["runs"]["teams"], [
            team("max", 1, 1, 1, 1.0, 0, 2, 2, disputed=0, taken_back=0)])


def took(points=None, unrated=0):
    """A team's usage that took only `points` and `unrated` of its orchestrator's seats."""
    return {**EMPTY, "orchestrator": {"points": points or {}, "unrated": unrated}}


class ModelsJsonTeamUsage(WeekMeters):
    seat, turn = run_usage.ModelsJsonRunUsage.seat, run_usage.ModelsJsonRunUsage.turn

    def teams(self, runs):
        """`runs`, each reviewed once in round 1, and `ak models --json`'s `runs`."""
        history(self.home, runs, [(row["run_id"], 1, "medium") for row in runs])
        return self.answer(TABLES)["runs"]

    def test_each_team_s_usage_sums_its_tasks_and_relaunches_not_follow_ups(self):
        # acme/Max: 100 pts/M for anvil-1; brine/Plus: 100/3 pts/M for bolt-1
        self.read(50, 10)
        self.seat(45, 100_000, model="anvil-1")
        self.read(40, 20)
        self.read(50, 0, plan="Plus", provider="brine")
        self.seat(45, 300_000, model="bolt-1", harness="chime")
        self.read(40, 10, plan="Plus", provider="brine")
        runs = [
            run("fix-api", 5),
            run("fix-docs", 4),
            run("write-cache", 3, executor_effort="low", **FAILED),
            run("finish-cache", 2, change="write-cache", executor="crux"),
            run("fix-quiet", 2, executor_effort="high"),
            run("fix-api-again", 1, kind="follow-up"),
            run("fix-old", 31),
            run("fix-old-again", 1, change="fix-old"),
        ]
        reviews = [(row["run_id"], 1, "medium") for row in runs if row["run_id"] != "finish-cache"]
        # team max: build (10 pts + 2,000 unrated) and review summing exactly to 10 + 1/300
        self.turn(35, (100_000, 0, 0, 0), run_id="fix-api", role="executor")
        self.turn(35, (2_000, 0, 0, 0), model="anvil-9", run_id="fix-api", role="executor")
        self.turn(35, (100_000, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="fix-api", role="reviewer")
        self.turn(35, (200_000, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="fix-docs", role="reviewer")
        self.turn(35, (100, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="fix-docs", role="reviewer")
        # team low: relaunch's build joins write-cache's to sum to 10; its review joins too
        self.turn(35, (100_000, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="write-cache", role="executor")
        self.turn(35, (200_000, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="finish-cache", role="executor")
        self.turn(35, (3_000, 0, 0, 0), model="bolt-9", harness="chime",
                  run_id="finish-cache", role="reviewer")
        # follow-up and out-of-window relaunch: in no team, kept in runs.usage
        self.turn(35, (50_000, 0, 0, 0), run_id="fix-api-again", role="executor")
        self.turn(35, (1_000, 0, 0, 0), model="anvil-9", run_id="fix-api-again", role="executor")
        self.turn(35, (30_000, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="fix-api-again", role="reviewer")
        self.turn(35, (500, 0, 0, 0), model="bolt-9", harness="chime",
                  run_id="fix-api-again", role="reviewer")
        self.turn(35, (20_000, 0, 0, 0), run_id="fix-old-again", role="executor")
        history(self.home, runs, reviews)
        found = self.answer(TABLES)["runs"]
        self.assertCountEqual(found["teams"], [
            team("max", 2, 2, 2, 2.0, 2, 2, usage={**EMPTY,
                "executor": {"points": {"acme": {"Max": 10}}, "unrated": 2_000},
                "reviewer": {"points": {"brine": {"Plus": 10.0033}}, "unrated": 0}}),
            team("low", 1, 0, 1, 2.0, 1, 1, usage={**EMPTY,
                "executor": {"points": {"brine": {"Plus": 10}}, "unrated": 0},
                "reviewer": {"points": {}, "unrated": 3_000}}),
            team("high", 1, 1, 1, 1.0, 1, 1, usage=EMPTY)])
        self.assertEqual(found["usage"], {
            "executor": {"points": {"acme": {"Max": 17}, "brine": {"Plus": 10}}, "unrated": 3_000},
            "reviewer": {"points": {"brine": {"Plus": 11.0033}}, "unrated": 3_500},
            "orchestrator": {"points": {"acme": {"Max": 10}, "brine": {"Plus": 10}}, "unrated": 0}})

    def test_one_orchestrator_s_seats_divide_over_its_teams_by_their_tasks(self):
        # acme/Max: 100 pts/M for anvil-1; nova at high took 10 points and 2,002 unrated tokens
        self.read(50, 10)
        self.seat(45, 100_000, orchestrator="nova", effort="high")
        self.read(40, 20)
        self.seat(35, 2_002, model="anvil-9", orchestrator="nova", effort="high")
        found = self.teams([run("fix-api", 5), run("fix-docs", 4), run("fix-cache", 3),
                            run("fix-login", 2, executor_effort="low")])
        # 3/4 and 1/4: 1,501.5 and 500.5 tokens, each rounded half to even
        self.assertCountEqual(found["teams"], [
            team("max", 3, 3, 3, 3.0, 3, 3, usage=took({"acme": {"Max": 7.5}}, 1_502)),
            team("low", 1, 1, 1, 1.0, 1, 1, usage=took({"acme": {"Max": 2.5}}, 500))])

    def test_teams_of_no_orchestrator_effort_share_the_seats_of_no_name(self):
        self.read(50, 10)
        self.seat(45, 100_000)                                  # no name, no effort: 10 points
        self.read(40, 20)
        self.seat(35, 3_000, orchestrator="nova")              # nova's, of no effort
        found = self.teams([run("fix-api", 5, orchestrator_effort=None),
                            run("fix-docs", 4, orchestrator="vega", orchestrator_effort=None),
                            run("fix-cache", 3, orchestrator="vega", orchestrator_effort=None)])
        self.assertCountEqual(found["teams"], [
            team("max", 1, 1, 1, 1.0, 1, 1, orchestrator_effort=None,
                 usage=took({"acme": {"Max": 3.33333}})),
            team("max", 2, 2, 2, 2.0, 2, 2, orchestrator="vega", orchestrator_effort=None,
                 usage=took({"acme": {"Max": 6.66667}}))])

    def test_seats_no_team_matches_stay_in_seats_alone_and_a_team_none_matches_holds_zeros(self):
        self.read(50, 10)
        self.seat(45, 100_000, orchestrator="nova", effort="low")
        self.read(40, 20)
        found = self.teams([run("fix-api", 5)])                 # nova at high
        self.assertEqual(found["teams"], [team("max", 1, 1, 1, 1.0, 1, 1, usage=took())])
        self.assertEqual(found["seats"], [
            {"name": "nova", "effort": "low", "points": {"acme": {"Max": 10}}, "unrated": 0}])


if __name__ == "__main__":
    unittest.main()
