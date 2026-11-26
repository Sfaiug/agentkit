"""`ak models --json` gives each role's models by the tasks they did with the team now (`own`).
The team now: each role's models [defaults] holds, in the order held, each at the effort a run
launched now records.  A team of the last 30 days (`runs`, tests/
test_key_models_json_counts_tasks_by_team.py) has a role of the team now's where its model there
is one held for that role, at the effort held or at none recorded, a blank being none.  A role's
rows: a model at an effort that did that role in a team whose two other roles are both the team
now's, summing those teams; each model held its row at its effort now, in use, zeros where it did
nothing; those in use first in the order held, then most tasks, name and effort, none last.
`team` sums the teams all three of whose roles are the team now's.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
runs and their reviews written into the Home's history.db; judged by the output and exit code.
Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from test_key_models_json_counts_tasks_by_team import FAILED, history, run

# Each run nova high, bolt max, crux, as RUN in the key of the tasks by team, an hour of build,
# half of review, a quarter of checks and an hour waiting; its first review's effort medium
# unless REVIEWS says otherwise
RUNS = [
    run("fix-api", 1), run("fix-docs", 1, **FAILED),            # the team now's
    run("fix-login", 1, orchestrator_effort=None),              # an orchestrator's unrecorded
    run("fix-cache", 1),                                        # a reviewer's blank, and
    run("fix-menu", 1, **FAILED),                               # one never reviewed
    run("fix-auth", 1, executor="flux", executor_effort="high", reviewer="echo"),
    run("fix-mail", 1, reviewer="echo"),                        # the team now's builder, for echo
    run("fix-ci", 1, executor_effort="low"),                    # held after it, sorted before
    run("fix-cd", 1, executor_effort="high", **FAILED),
    run("fix-cli", 1, executor_effort=None, **FAILED),          # a builder's effort unrecorded
    run("fix-gale", 1, executor="gale", executor_effort="high"),
    run("fix-gale-again", 1, executor="gale", executor_effort="high"),
    run("fix-ash", 1, executor="ash", executor_effort="high", **FAILED),
    run("fix-sage", 1, orchestrator="sage"),
]
REVIEWS = [(row["run_id"], 1, "" if row["run_id"] == "fix-cache" else "medium")
           for row in RUNS if row["run_id"] != "fix-menu"]


def summed(tasks, live, first_pass=None, reviews=None, issues=0, disputed=0, taken_back=0):
    return {"tasks": tasks, "live": live,
            "first_pass": tasks if first_pass is None else first_pass,
            "reviews": tasks if reviews is None else reviews, "issues": issues,
            "disputed": disputed, "taken_back": taken_back,
            "hours": {"build": tasks, "review": tasks / 2, "checks": tasks / 4, "waiting": tasks}}


def row(name, effort, in_use, tasks, live, first_pass=None, reviews=None, issues=0, **disputes):
    return {"name": name, "effort": effort, "in_use": in_use,
            **summed(tasks, live, first_pass, reviews, issues, **disputes)}


def own_of(runs, reviews, findings=None):
    with Home() as home:
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, {"nova": "claude", "bolt": {"harness": "codex", "effort": "max",
                                                         "review_effort": "high"},
                              "crux": {"harness": "codex", "effort": "medium"},
                              "dune": {"harness": "codex", "effort": "low"}},
                       orchestrator="nova", workers=["dune", "bolt"],
                       reviewers=["crux", "bolt"])
        home.write(".agentkit/state/boards.json", boards())
        history(home, runs, reviews, findings)
        return home.ak("models", "--json", env=ENV)


class ModelsJsonOwnRows(unittest.TestCase):
    def test_each_role_s_rows_with_the_team_now(self):
        done = own_of(RUNS, REVIEWS)
        self.assertEqual(done.code, 0, done.err)
        own = json.loads(done.out)["own"]
        # fix-api, fix-docs, and those of an effort not recorded: fix-login, fix-cache, fix-menu
        # and fix-cli; fix-menu was never reviewed
        self.assertEqual(own["team"], summed(6, 3, 5, 5))
        self.assertEqual(own["orchestrator"], [
            row("nova", "high", True, 5, 2, 4, 4), row("nova", None, False, 1, 1),
            row("sage", "high", False, 1, 1)])
        # flux built for echo alone, and bolt's build for echo is in none of bolt's rows; dune,
        # held, did nothing
        self.assertEqual(own["executor"], [
            row("dune", "low", True, 0, 0), row("bolt", "max", True, 5, 3, 4, 4),
            row("gale", "high", False, 2, 2), row("ash", "high", False, 1, 0),
            row("bolt", "high", False, 1, 0), row("bolt", "low", False, 1, 1),
            row("bolt", None, False, 1, 0)])
        # a blank effort and none are one row; bolt, held for both roles, reviewed nothing
        self.assertEqual(own["reviewer"], [
            row("crux", "medium", True, 4, 2), row("bolt", "high", True, 0, 0),
            row("crux", None, False, 2, 1, 1, 1), row("echo", "medium", False, 1, 1)])

    def test_a_role_s_row_sums_first_pass_reviews_and_issues_over_its_teams(self):
        runs = [
            run("fix-api", 1),
            run("fix-docs", 1, orchestrator_effort=None),
            run("fix-cache", 1, **FAILED),
            run("fix-mail", 1, reviewer="echo"),            # another reviewer: outside bolt's row
        ]
        reviews = [
            ("fix-api", 1, "medium", "PASS", 0),
            ("fix-docs", 1, "medium", "FAIL", 2), ("fix-docs", 2, "high", "PASS", 0),
            ("fix-cache", 1, "", "FAIL", 3), ("fix-cache", 2, "", "FAIL", 1),
            ("fix-mail", 1, "medium", "PASS", 5),
        ]
        done = own_of(runs, reviews)
        self.assertEqual(done.code, 0, done.err)
        own = json.loads(done.out)["own"]
        self.assertEqual(own["team"], summed(3, 2, 1, 5, 6))
        self.assertEqual(own["orchestrator"], [
            row("nova", "high", True, 2, 1, 1, 3, 4), row("nova", None, False, 1, 1, 0, 2, 2)])
        self.assertEqual(own["executor"], [
            row("dune", "low", True, 0, 0), row("bolt", "max", True, 3, 2, 1, 5, 6)])
        self.assertEqual(own["reviewer"], [
            row("crux", "medium", True, 2, 2, 1, 3, 2), row("bolt", "high", True, 0, 0),
            row("crux", None, False, 1, 0, 0, 2, 4), row("echo", "medium", False, 1, 1, 1, 1, 5)])

    def test_a_role_s_row_sums_disputed_and_taken_back_over_its_teams(self):
        runs = [run("fix-api", 1), run("fix-docs", 1, orchestrator_effort=None),
                run("fix-mail", 1, reviewer="echo")]       # another reviewer: outside bolt's row
        reviews = [(run_id, 1, "medium") for run_id in ("fix-api", "fix-docs", "fix-mail")]
        # each finding answered, `conceded` and `dropped` taken back
        findings = [("fix-api", "upheld"), ("fix-api", "conceded"), ("fix-docs", "dropped"),
                    ("fix-mail", "conceded"), ("fix-mail", "upheld")]
        done = own_of(runs, reviews, findings)
        self.assertEqual(done.code, 0, done.err)
        own = json.loads(done.out)["own"]
        self.assertEqual(own["team"], summed(2, 2, disputed=3, taken_back=2))
        self.assertEqual(own["orchestrator"], [
            row("nova", "high", True, 1, 1, disputed=2, taken_back=1),
            row("nova", None, False, 1, 1, disputed=1, taken_back=1)])
        self.assertEqual(own["executor"], [
            row("dune", "low", True, 0, 0), row("bolt", "max", True, 2, 2, disputed=3,
                                                taken_back=2)])
        self.assertEqual(own["reviewer"], [
            row("crux", "medium", True, 2, 2, disputed=3, taken_back=2),
            row("bolt", "high", True, 0, 0),
            row("echo", "medium", False, 1, 1, disputed=2, taken_back=1)])


if __name__ == "__main__":
    unittest.main()
