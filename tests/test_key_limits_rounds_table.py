"""Under `review_rounds` on `config · limits`, what your tasks took by the review rounds they went
through (`ak models --json`'s `runs.rounds`, tests/test_key_models_json_counts_tasks_by_rounds.py):
a row per number of rounds, fewest first, its cells written as the table under
`rescope_findings` writes its own (tests/test_key_limits_first_issues_table.py) -- ending `over`
above the rounds held, off marking none, following ← and →: its tasks went on through a
relaunch or an extra round; fixed columns where the table fits, folded rows with named numbers
where it does not.

The owner's ask of 24 Nov 2026: "a real way to visualize this data, work with it and from it be
abel to make the best decision".  Black-box: history.db rows in the Home, `AK_BIN` in a
person's terminal (tests/fixtures/akterm.py), judged by the screen without colour; it fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from test_key_limits_first_issues_table import paid_home
from test_key_limits_size_table import drawn, opened, wider
from test_key_models_json_counts_tasks_by_team import FAILED, run

HEADING = ("What your tasks took, by the review rounds they went through · last 30 days",)
# (rounds, tasks, tasks live): each task spends RUN's 1 h build, 0.5 h review, 0.25 h checks and
# 1 h waiting, a review in each of its rounds
ROWS = [(1, 20, 16), (2, 20, 10), (3, 20, 0), (4, 20, 5), (5, 5, 0)]
# 1's 12 points of ChatGPT Pro ($200): 12 * $200 / 100 * 12 / 52 over 16 tasks live, $0.35
TABLE = ["rounds  tasks  went live    time  usage",
         "1          20        80%   3.4 h  $0.35",
         "2          20        50%   5.5 h      -",
         "3          20         0%              -",
         "4          20        25%  11.0 h      -",
         "5           5"]


def over(table, *rows):
    """`table` with its rows at `rows` ending `over`."""
    return [f"{line:<{len(table[0]) + 2}}over" if at in rows else line
            for at, line in enumerate(table)]


def open_at(case, limit, rows=ROWS, size=(100, 40)):
    """A Home of its own with a task per `rows`, round 1's first building 12 points of ChatGPT
    Pro, and `review_rounds = limit`, opened on that row."""
    names = [(rounds, f"fix-api-{rounds}-{n}", n < live)
             for rounds, tasks, live in rows for n in range(tasks)]
    home = paid_home(case, {"review_rounds": limit},
                     [run(name, 1 + at / 10, rounds_used=rounds, **({} if live else FAILED))
                      for at, (rounds, name, live) in enumerate(names)],
                     [(name, at, "medium") for rounds, name, _ in names
                      for at in range(1, rounds + 1)], "fix-api-1-0")
    return opened(case, home, "Review rounds", size=size)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RoundsTable(unittest.TestCase):
    def test_at_100_cells_each_number_of_rounds_shows_its_numbers_for_every_task_live(self):
        open_at(self, 3).wait(drawn(over(TABLE, 4, 5), HEADING))

    def test_left_moves_the_mark_onto_the_row_it_now_passes_and_off_marks_none(self):
        term = open_at(self, 3)
        term.wait(drawn(over(TABLE, 4, 5), HEADING))
        for arrows, table in ((["Left"], over(TABLE, 3, 4, 5)),
                              (["Right"], over(TABLE, 4, 5)),
                              (["Left"] * 3, TABLE)):
            term.keys(*arrows)
            term.wait(drawn(table, HEADING))

    def test_with_no_task_the_heading_says_none_yet(self):
        shown = open_at(self, 3, rows=[]).wait(lambda screen: (
            "  What your tasks took, by the review rounds they went through · none yet"
            in map(str.rstrip, screen.split("\n"))))
        self.assertNotIn("rounds  tasks", shown)

    def test_at_40_cells_rows_fold_with_named_numbers_and_fit_the_terminal(self):
        term = open_at(self, 3, size=(40, 50))
        shown = term.wait(drawn(["1  20 tasks",
                                 "  went live 80%  time 3.4 h",
                                 "  usage $0.35",
                                 "2  20 tasks",
                                 "  went live 50%  time 5.5 h  usage -",
                                 "3  20 tasks",
                                 "  went live 0%  usage -",
                                 "4  20 tasks  over",
                                 "  went live 25%  time 11.0 h  usage -",
                                 "5  5 tasks  over"],
                                ["What your tasks took, by the review",
                                 "rounds they went through · last 30",
                                 "days"]))
        self.assertNotIn("rounds  tasks", shown)
        self.assertFalse(wider(term, 40))


if __name__ == "__main__":
    unittest.main()
