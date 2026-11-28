"""Under `orchestrator_lines` on `config · limits`, what a seat's own changes of each size took
(`ak models --json`'s `runs.own_sizes`, tests/test_key_models_json_counts_own_changes_by_size.py),
written as the table of tasks by size under `executor_lines` writes its own
(tests/test_key_limits_size_table.py), so what a line costs reads the same in both: a row per 25
lines, smallest first -- its changes, from 20 of them the share that went live, and with a line
live each part's hours for every 100 lines live, `fixing` a run's builder's, and what they took
in all three roles together for every 100 lines live as money -- marked `over` wholly above the
limit; fixed columns where the table fits, folded rows with named numbers where it does not.

The owner's ask of 24 Nov 2026: "this hides the cost of own tests and time".  Black-box:
history.db rows in the Home, `AK_BIN` in a person's terminal (tests/fixtures/akterm.py), judged
by the screen without colour; it fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from test_key_limits_first_issues_table import paid_home
from test_key_limits_size_table import drawn, opened, wider
from test_key_models_json_counts_tasks_by_team import FAILED, run

HEADING = ("What your own changes of each size took, for every 100 lines that went live · "
           "last 30 days",)
# (first review's lines, changes, changes live): each change one run of RUN's 1 h build, 0.5 h
# review, 0.25 h checks and 1 h waiting
ROWS = [(25, 20, 16), (50, 20, 10), (75, 20, 0)]
# 1–25's over 400 lines live: 20 h fixing, 10 h review, 5 h checks (1.25 h, round half to even),
# 20 h waiting, and pr-25-0's 12 points of ChatGPT Pro ($200): 12 * $200 / 100 * 12 / 52 / 4
TABLE = ["lines  changes  went live  fixing  reviewing  own tests  waiting  usage",
         "1–25        20        80%   5.0 h      2.5 h      1.2 h    5.0 h  $1.38",
         "26–50       20        50%   4.0 h      2.0 h      1.0 h    4.0 h      -",
         "51–75       20         0%                                             -  over"]


def open_at(case, rows=ROWS, paid="pr-25-0", size=(100, 40)):
    """A Home of its own (`paid_home`) with an own change per `rows`, `paid` fixing 12 points of
    ChatGPT Pro, and `orchestrator_lines = 50`, opened on that row."""
    names = [(lines, f"pr-{lines}-{n}", n < live)
             for lines, changes, live in rows for n in range(changes)]
    home = paid_home(case, {"orchestrator_lines": 50},
                     [run(name, 1 + at / 10, kind="seat PR", change=f"acme/api#{at}",
                          first_review_lines=lines, **({} if live else FAILED))
                      for at, (lines, name, live) in enumerate(names)], [], paid)
    return opened(case, home, "Max lines per orchestrator task", size=size)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OwnSizeTable(unittest.TestCase):
    def test_at_100_cells_each_size_shows_its_numbers_and_over_above_the_limit(self):
        open_at(self).wait(drawn(TABLE, HEADING))

    def test_a_row_of_under_20_changes_shows_its_changes_alone(self):
        # 26–50 has 19 changes, all live and paid, yet shows its changes alone
        open_at(self, rows=[(25, 20, 16), (50, 19, 19)], paid="pr-50-0").wait(drawn(
            [TABLE[0], f"{TABLE[1][:-5]}    -", "26–50       19"], HEADING))

    def test_at_40_cells_rows_fold_with_named_numbers_and_fit_the_terminal(self):
        term = open_at(self, size=(40, 50))
        shown = term.wait(drawn(["1–25  20 changes",
                                 "  went live 80%  fixing 5.0 h",
                                 "  reviewing 2.5 h  own tests 1.2 h",
                                 "  waiting 5.0 h  usage $1.38",
                                 "26–50  20 changes",
                                 "  went live 50%  fixing 4.0 h",
                                 "  reviewing 2.0 h  own tests 1.0 h",
                                 "  waiting 4.0 h  usage -",
                                 "51–75  20 changes  over",
                                 "  went live 0%  usage -"],
                                ["What your own changes of each size",
                                 "took, for every 100 lines that went",
                                 "live · last 30 days"]))
        self.assertNotIn("lines  changes", shown)
        self.assertFalse(wider(term, 40))


if __name__ == "__main__":
    unittest.main()
