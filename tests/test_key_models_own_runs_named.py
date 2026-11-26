"""`ak models` names each row of its role tables as every screen names that model at its effort:
one at effort `none` is the model's name alone, and a configured name holding ` @ ` is a name,
never a model and an effort.  `--json` keys ak's own numbers by model and effort (`live`) alike,
such a name's own @ doubled, never a row of the model's runs at that effort.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
judged runs, or the tasks as tests/test_key_models_json_counts_tasks_by_team.py writes them,
in the Home's history.db; judged by the output and exit code.  Fails against /bin/false.
"""

import json
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from test_key_models_json_counts_tasks_by_team import history, run
from test_key_models_own_tables import HEADS

HAIKU = {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}
# a run haiku executed at effort none, merged in round 1
RUN = {"run_id": "acme-none", "repo": "acme", "executor": "haiku", "executor_effort": "none",
       "final_state": "pass", "verdict": "PASS", "rounds_used": 1, "changed_lines": 1,
       "started_at": 1, "finished_at": 2}


def ran(home, *runs):
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    with connection:
        connection.execute(f"CREATE TABLE runs ({', '.join(RUN)})")
        connection.executemany(f"INSERT INTO runs VALUES ({', '.join('?' * len(RUN))})",
                               [tuple({**RUN, **run}.values()) for run in runs])
    connection.close()


# each table's heading line, at its words
HEAD = {word: [word, *heads.split()] for word, heads in HEADS.items()}


class OwnRunsNamed(unittest.TestCase):
    def test_effort_none_and_a_name_holding_an_at_are_said_as_the_model_s_name(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")
            akconfig.write(home, {"haiku": {**HAIKU, "effort": "max"}, "haiku @ max": HAIKU},
                           orchestrator="haiku @ max", workers=["haiku"])
            home.write(".agentkit/state/boards.json", boards())
            # a task of the team now, its orchestrator at effort none; then one `haiku @ max`
            # built at an effort not recorded
            team = {"orchestrator": "haiku @ max", "orchestrator_effort": "none",
                    "executor": "haiku", "reviewer": "haiku"}
            history(home, [run("fix-api", 1, **team),
                           run("fix-docs", 1, **{**team, "executor": "haiku @ max",
                                                 "executor_effort": None})],
                    [("fix-api", 1, "max"), ("fix-docs", 1, "max")])
            done = home.ak("models", env={**ENV, "COLUMNS": "120"})
        self.assertEqual(done.code, 0, done.err)
        shown = [line.split() for line in done.out.splitlines()]
        self.assertEqual(shown[shown.index(HEAD["ORCHESTRATOR"]):], [
            HEAD["ORCHESTRATOR"], ["●", "Haiku", "4.5", "1"], [],
            HEAD["BUILDER"], ["■", "Haiku", "4.5", "max", "1"], ["□", "Haiku", "4.5", "1"],
            [],
            HEAD["REVIEWER"], ["■", "Haiku", "4.5", "max", "1"]])

    def test_a_run_at_an_effort_stays_apart_from_a_name_holding_it(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")
            akconfig.write(home, {"haiku": {**HAIKU, "effort": "max"}, "haiku @ max": HAIKU})
            home.write(".agentkit/state/boards.json", boards())
            ran(home, {"executor_effort": "max"},
                {"run_id": "acme-unrecorded", "executor": "haiku @ max", "executor_effort": None})
            done = home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.err)
        live = json.loads(done.out)["live"]
        self.assertEqual({key: roles["execute"] for key, roles in live.items()},
                         {"haiku @ max": {"runs": 1, "round_1": 100},
                          "haiku @@ max": {"runs": 1, "round_1": 100}})


if __name__ == "__main__":
    unittest.main()
