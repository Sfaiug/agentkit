"""Under `rescope_findings` on `config · limits`, what your tasks took by the issues their first
review found (`ak models --json`'s `runs.first_issues`,
tests/test_key_models_json_counts_tasks_by_first_issues.py): a row per number of issues, fewest
first, none made of several -- its tasks, from 20 of them the share that went live, and with a
task live the hours its tasks spent and what they took in all three roles as money, each for
every task live, as the size table writes them (tests/test_key_limits_size_table.py) -- ending
`ends the run` at or above the limit, off marking none, following ← and →; fixed columns where
the table fits, folded rows with named numbers where it does not.

The owner's ask of 24 Nov 2026: "at what point should a task be rewritten or split depending on
how many isues the reviewer finds".  Black-box: history.db rows in the Home, `AK_BIN` in a
person's terminal (tests/fixtures/akterm.py), judged by the screen without colour; it fails
against `/bin/false`.
"""

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from test_key_limits_size_table import MODELS, drawn, opened, wider
from test_key_models_json_counts_tasks_by_team import FAILED, history, run
from test_key_models_json_run_usage import TABLES
from test_key_models_json_week_meters import DAY, HOUR, NOW, THEN

HEADING = "What your tasks took, by the issues their first review found"
# (issues, tasks, tasks live): each task spends RUN's 1 h build, 0.5 h review, 0.25 h checks
# and 1 h waiting
ROWS = [(0, 20, 16), (2, 20, 10), (6, 20, 0), (8, 5, 0)]
# 0's 12 points of ChatGPT Pro ($200): 12 * $200 / 100 * 12 / 52 over 16 tasks live, $0.35
TABLE = ["issues  tasks  went live   time  usage",
         "0          20        80%  3.4 h  $0.35",
         "2          20        50%  5.5 h      -",
         "6          20         0%             -",
         "8           5"]
END = "ends the run"


def ended(table, *rows):
    """`table` with its rows at `rows` ending `ends the run`."""
    return [f"{line:<{len(table[0]) + 2}}{END}" if at in rows else line
            for at, line in enumerate(table)]


def open_at(case, limit, rows=ROWS, paid="fix-api-0-0", size=(100, 40)):
    """A Home of its own (`paid_home`) with a task per `rows` and `rescope_findings = limit`,
    opened on that row."""
    names = [(issues, f"fix-api-{issues}-{n}", n < live)
             for issues, tasks, live in rows for n in range(tasks)]
    home = paid_home(case, {"rescope_findings": limit},
                     [run(name, 1 + at / 10, **({} if live else FAILED))
                      for at, (_, name, live) in enumerate(names)],
                     [(name, 1, "medium", "FAIL", issues) for issues, name, _ in names], paid)
    return opened(case, home, "Findings that end a run for rescoping", size=size)


def paid_home(case, settings, runs, reviews, paid):
    """A Home of its own holding `runs` and `reviews` (`history`), `paid` building 12 points of
    ChatGPT Pro, its config.toml setting `settings`."""
    home = Home()
    case.addCleanup(home.close)
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS, settings=settings,
                   providers={"openai": {"mode": "subscription", "accounts": ["default"]}})
    history(home, runs, reviews)
    week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
    home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
        "openai": {"accounts": {"default": {"meters": [week]}}}}})
    turn = home.path / f".agentkit/runs/{paid}/round-1/executor-default"
    turn.mkdir(parents=True)
    (turn / "harness").write_text("codex")
    used = {"meter_readings": [("openai", "default", "weekly", used, THEN + DAY, 7 * DAY,
                                THEN - ago * HOUR, "probe", "pro", None)
                               for ago, used in ((50, 0), (40, 12))],
            "turn_usage": [(paid, "executor", str(turn), "default", "bolt-3", THEN - 45 * HOUR,
                            100_000, 0, 0, 0)]}
    with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
        for table, items in used.items():
            db.execute(f"CREATE TABLE {table} ({TABLES[table]})")
            db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(items[0]))})", items)
    return home


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FirstIssuesTable(unittest.TestCase):
    def test_at_100_cells_each_number_shows_its_numbers_for_every_task_live(self):
        open_at(self, 6).wait(drawn(ended(TABLE, 3, 4), (f"{HEADING} · last 30 days",)))

    def test_a_row_of_under_20_tasks_shows_its_tasks_alone_and_rows_stay_apart(self):
        # 7 has 19 tasks, all live and paid, yet shows its tasks alone; 9 stays a row of its own
        term = open_at(self, 6, rows=[(0, 20, 16), (7, 19, 19), (9, 20, 10)], paid="fix-api-7-0")
        term.wait(drawn(["issues  tasks  went live   time  usage",
                         "0          20        80%  3.4 h      -",
                         f"7          19                           {END}",
                         f"9          20        50%  5.5 h      -  {END}"],
                        (f"{HEADING} · last 30 days",)))

    def test_left_moves_the_mark_onto_the_row_it_now_reaches_and_off_marks_none(self):
        term = open_at(self, 7)
        term.wait(drawn(ended(TABLE, 4), (f"{HEADING} · last 30 days",)))
        for arrows, table in ((["Left"], ended(TABLE, 3, 4)),
                              (["Right"], ended(TABLE, 4)),
                              (["Left"] * 7, TABLE)):
            term.keys(*arrows)
            term.wait(drawn(table, (f"{HEADING} · last 30 days",)))

    def test_with_no_task_the_heading_says_none_yet(self):
        shown = open_at(self, 6, rows=[]).wait(
            lambda screen: f"  {HEADING} · none yet" in map(str.rstrip, screen.split("\n")))
        self.assertNotIn("issues  tasks", shown)

    def test_at_40_cells_rows_fold_with_named_numbers_and_fit_the_terminal(self):
        term = open_at(self, 6, size=(40, 50))
        shown = term.wait(drawn(["0  20 tasks",
                                 "  went live 80%  time 3.4 h",
                                 "  usage $0.35",
                                 "2  20 tasks",
                                 "  went live 50%  time 5.5 h  usage -",
                                 f"6  20 tasks  {END}",
                                 "  went live 0%  usage -",
                                 f"8  5 tasks  {END}"],
                                ["What your tasks took, by the issues",
                                 "their first review found · last 30",
                                 "days"]))
        self.assertNotIn("issues  tasks", shown)
        self.assertFalse(wider(term, 40))


if __name__ == "__main__":
    unittest.main()
