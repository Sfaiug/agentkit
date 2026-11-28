"""`ak models`'s ORCHESTRATOR table shows `answers in` and `left out` between `went live` and
`time`, from `runs.seats`, and each orchestrator row of `ak models --json`'s `own` carries the
four counts (`turns`, `turn_seconds`, `checks`, `gaps`): `answers in` is the median of its turns
(`69 s` below two minutes, `4.2 min` from there, `1.5 h` from an hour), `left out` the asks its
done checks found missing per check to a tenth, each `-` below 20 turns or checks; a row below 20
tasks shows its tasks alone, and the note under the tables names both.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_own_tables.py sets it up,
with `seat_turns` and `done_checks` in the Home's history.db; judged by the output and exit code.
Fails against /bin/false.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akboards import ENV, boards
from test_key_models_json_counts_turns_and_done_checks import TABLES
from test_key_models_json_week_meters import HOUR, THEN
from test_key_models_own_tables import NOVA, WIDE, home_of


def with_seat_work(teams, turns=(), checks=()):
    """`home_of(teams)` with `seat_turns` rows `(orchestrator, effort, seconds)` and `done_checks`
    rows `(model, effort, gaps)` inside the 30-day window."""
    home = home_of(teams)
    with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
        for table in ("seat_turns", "done_checks"):
            db.execute(f"CREATE TABLE {table} ({TABLES[table]})")
        db.executemany(
            "INSERT INTO seat_turns VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(f"claude:turn-{n}", "acme", THEN - 20 * HOUR, seconds, "default", model, effort)
             for n, (model, effort, seconds) in enumerate(turns)])
        db.executemany(
            "INSERT INTO done_checks VALUES (?, ?, ?, ?, ?)",
            [("acme", model, effort, THEN - 20 * HOUR, gaps)
             for model, effort, gaps in checks])
    return home


def shown(home, columns=WIDE):
    done = home.ak("models", env={**ENV, "COLUMNS": str(columns)})
    assert done.code == 0, done.err
    return done.out.splitlines()


class ModelsOrchestratorColumns(unittest.TestCase):
    def test_answers_in_and_left_out_show_for_an_orchestrator_with_enough_turns_and_checks(self):
        # nova high: 30 turns with median 69 s (15 at 60, 15 at 78) and 20 checks totalling 66
        # gaps (3.3 per check); sage high: 20 turns at 252 s (4.2 min) and 20 clean checks (0.0);
        # alto high: 20 turns at 5400 s (1.5 h) and 20 checks with 7 gaps (0.4, exact half-to-even)
        turns = ([("nova", "high", 60)] * 15 + [("nova", "high", 78)] * 15
                 + [("sage", "high", 252)] * 20 + [("alto", "high", 5400)] * 20)
        checks = ([("nova", "high", 3)] * 14 + [("nova", "high", 4)] * 6
                  + [("sage", "high", 0)] * 20 + [("alto", "high", 1)] * 7
                  + [("alto", "high", 0)] * 13)
        teams = [("nova", 20, 20, {}),
                 ("sage", 20, 20, {"orchestrator": "sage", "orchestrator_effort": "high"}),
                 ("alto", 20, 20, {"orchestrator": "alto", "orchestrator_effort": "high"})]
        with with_seat_work(teams, turns, checks) as home:
            wide = shown(home)
            folded = shown(home, 40)
            home.write(".agentkit/state/boards.json", boards())
            as_json = home.ak("models", "--json", env=ENV)
        self.assertEqual(as_json.code, 0, as_json.err)
        at = next(i for i, line in enumerate(wide) if line.startswith("ORCHESTRATOR"))
        self.assertEqual(wide[at:at + 4], [
            f"ORCHESTRATOR{' ' * 13}tasks  went live  answers in  left out   time  usage",
            f"● {NOVA} high     20       100%        69 s       3.3  2.8 h      -",
            f"○ alto high{' ' * 17}20       100%       1.5 h       0.4  2.8 h      -",
            f"○ sage high{' ' * 17}20       100%     4.2 min       0.0  2.8 h      -"])
        # narrow terminal folds the two columns as the others do
        self.assertIn("  tasks 20  went live 100%", folded)
        self.assertIn("  answers in 69 s  left out 3.3", folded)
        # `--json` carries the four numbers on each orchestrator row
        orch = {row["name"]: {key: row[key] for key in ("turns", "turn_seconds", "checks", "gaps")}
                for row in json.loads(as_json.out)["own"]["orchestrator"]}
        self.assertEqual(orch, {
            "nova": {"turns": 30, "turn_seconds": 69, "checks": 20, "gaps": 66},
            "alto": {"turns": 20, "turn_seconds": 5400, "checks": 20, "gaps": 7},
            "sage": {"turns": 20, "turn_seconds": 252, "checks": 20, "gaps": 0}})

    def test_below_few_turns_or_checks_shows_dashes_and_few_tasks_shows_tasks_alone(self):
        # nova high: 20 tasks, 5 turns and no checks -> `-` twice;
        # sage high: 19 tasks with 30 turns and 20 checks -> tasks alone
        turns = [("nova", "high", 69)] * 5 + [("sage", "high", 69)] * 30
        checks = [("sage", "high", 3)] * 20
        teams = [("nova", 20, 20, {}),
                 ("sage", 19, 19, {"orchestrator": "sage", "orchestrator_effort": "high"})]
        with with_seat_work(teams, turns, checks) as home:
            wide = shown(home)
        at = next(i for i, line in enumerate(wide) if line.startswith("ORCHESTRATOR"))
        self.assertEqual(wide[at:at + 3], [
            f"ORCHESTRATOR{' ' * 13}tasks  went live  answers in  left out   time  usage",
            f"● {NOVA} high     20       100%           -         -  2.8 h      -",
            f"○ sage high{' ' * 17}19"])

    def test_the_note_explains_answers_in_and_left_out(self):
        with with_seat_work([("nova", 20, 20, {})]) as home:
            note = "\n".join(shown(home)[-3:])
        self.assertIn("answers in: half its turns take no longer", note)
        self.assertIn("left out: what you asked for that a finished job lacked, per check", note)


if __name__ == "__main__":
    unittest.main()
