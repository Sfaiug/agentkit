"""`ak models` prints under its boards a line on the team now and a table a role of `own`, as
`--json` gives it (tests/test_key_models_json_own_rows.py): the team now's tasks, those that went
live and per task live the hours they spent and of them waiting; then each role's rows in
`own`'s order, those in use marked, each with its tasks, the share that went live and that
passed its first review, its reviews and issues per task, and per task live every hour its tasks
spent.  A row of fewer than 20 tasks shows its tasks alone, one with none live no hours.  A model
is named as every screen names it at its effort, plain whatever its label holds, by the name its
runs kept once no longer configured or where its label drawn plain is empty.  All three tables
print, a history of one role's former model alone too; where their columns pass the edge every
row folds, no column headed: its model's line, then each number it shows after its column's
name, indented, no line passing the edge and no word that fits cut.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
tasks and their reviews written into the Home's history.db as
tests/test_key_models_json_counts_tasks_by_team.py writes them; judged by the output and exit
code.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from test_key_models_json_counts_tasks_by_team import FAILED, history, run

# The team now: nova orchestrating at high, bolt building at max, crux reviewing at medium,
# crux's label holding a terminal style, then one left open that, drawn with its effort, would
# take the effort's first letter; echo configured but in no role, its label a style alone
MODELS = {"nova": {"harness": "claude", "label": "Acme Nova Seven Preview"},
          "bolt": {"harness": "codex", "model": "bolt-3", "effort": "max"},
          "crux": {"harness": "codex", "model": "crux-2", "effort": "medium",
                   "label": "\x1b[1mCrux 2\x1b["},
          "echo": {"harness": "codex", "label": "\x1b[2m"}}
# (name, tasks, of them live, the team): the team now's; the same with nova's effort not
# recorded; gale, no longer configured, building; and echo reviewing.  Each task is one run of
# 2.75 hours, one of them waiting.
TEAMS = [("now", 24, 18, {}), ("unrecorded", 20, 5, {"orchestrator_effort": None}),
         ("gale", 19, 10, {"executor": "gale", "executor_effort": "high"}),
         ("echo", 30, 0, {"reviewer": "echo"})]
NOVA = "Acme Nova Seven Preview"
HEAD = "tasks  went live  passed 1st review  reviews per task  issues per task  per task live"
# The team now: the first two teams, 23 of 44 live, 121 hours, 44 of them waiting
TEAM = ["Your team now: 23 of 44 tasks went live,", "5.3 h per task live, 1.9 h of it waiting"]
# The widest page ak draws, on which the three tables fit as columns
WIDE = 120
# The numbers of the rows of the team now's first two teams
BOTH = "44        52%                36%               2.1              2.2          5.3 h"
OWN = [" ".join(TEAM), "",
       f"ORCHESTRATOR{' ' * 20}{HEAD}",
       f"● {NOVA} high     24        75%                54%               1.7              1.4"
       "          3.7 h",
       f"○ {NOVA}          20        25%                15%               2.6              3.2"
       "         11.0 h",
       "",
       f"BUILDER{' ' * 25}{HEAD}",
       f"■ Bolt 3 max{' ' * 23}{BOTH}",
       f"□ gale high{' ' * 24}19",
       "",
       f"REVIEWER{' ' * 24}{HEAD}",
       f"■ Crux 2[ medium{' ' * 19}{BOTH}",
       f"□ echo medium{' ' * 22}30         0%                 0%               3.0"
       "              4.0"]
# On 40 cells every row folds: its model's line, then each number it shows after its column's
# name, two to a line where they fit
FOLDED = [*TEAM, "", "ORCHESTRATOR", f"● {NOVA} high",
          "  tasks 24  went live 75%", "  passed 1st review 54%", "  reviews per task 1.7",
          "  issues per task 1.4", "  per task live 3.7 h",
          f"○ {NOVA}",
          "  tasks 20  went live 25%", "  passed 1st review 15%", "  reviews per task 2.6",
          "  issues per task 3.2", "  per task live 11.0 h",
          "", "BUILDER", "■ Bolt 3 max",
          "  tasks 44  went live 52%", "  passed 1st review 36%", "  reviews per task 2.1",
          "  issues per task 2.2", "  per task live 5.3 h",
          "□ gale high", "  tasks 19",
          "", "REVIEWER", "■ Crux 2[ medium",
          "  tasks 44  went live 52%", "  passed 1st review 36%", "  reviews per task 2.1",
          "  issues per task 2.2", "  per task live 5.3 h",
          "□ echo medium",
          "  tasks 30  went live 0%", "  passed 1st review 0%", "  reviews per task 3.0",
          "  issues per task 4.0"]


def reviews(run_id, n, live):
    """Task `n`'s reviews: a live one's first passes but every fourth's; a failed first finds two
    issues, then one more round passes where the task went live, two fail one each where not."""
    if live and n % 4:
        return [(run_id, 1, "medium")]
    return [(run_id, 1, "medium", "FAIL", 2), *([(run_id, 2, "medium")] if live else [
        (run_id, 2, "medium", "FAIL", 1), (run_id, 3, "medium", "FAIL", 1)])]


def home_of(teams):
    """A Home of MODELS, the team now [defaults], whose history holds `teams`' tasks."""
    home = Home()
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS, orchestrator="nova", workers=["bolt"], reviewers=["crux"])
    home.write(".agentkit/state/boards.json", boards())
    runs = [run(f"fix-{name}-{n}", n / 24, **fields, **({} if n < live else FAILED))
            for name, tasks, live, fields in teams for n in range(tasks)]
    history(home, runs, [review for name, tasks, live, _ in teams for n in range(tasks)
                         for review in reviews(f"fix-{name}-{n}", n, n < live)])
    return home


class ModelsOwnTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home_of(TEAMS)
        cls.addClassCleanup(cls.home.close)

    def own(self, columns, home=None):
        """What `ak models` prints on `columns` cells from its line on the team now on, every
        line it prints as wide as the terminal at most and none holding a terminal style."""
        done = (home or self.home).ak("models", env={**ENV, "COLUMNS": str(columns)})
        self.assertEqual(done.code, 0, done.err)
        shown = done.out.splitlines()
        self.assertEqual([line for line in shown if len(line) > columns], [], columns)
        self.assertNotIn("\x1b", done.out)
        return shown[next(n for n, line in enumerate(shown) if line.startswith("Your team now")):]

    def test_on_a_wide_page_each_role_s_rows_stand_under_their_headings(self):
        self.assertEqual(self.own(WIDE), OWN)

    def test_on_40_cells_each_number_follows_its_model_s_line_with_its_name(self):
        self.assertEqual(self.own(40), FOLDED)
        # narrower, a name too wide wraps at its words
        shown = self.own(26)
        at = shown.index("ORCHESTRATOR")
        self.assertEqual(shown[at:at + 4], ["ORCHESTRATOR", f"● {NOVA}", "  high",
                                            "  tasks 24  went live 75%"])

    def test_a_history_of_a_former_builder_alone_prints_all_three_tables(self):
        with home_of(TEAMS[2:3]) as home:
            self.assertEqual(self.own(WIDE, home), [
                "Your team now has no task yet", "",
                OWN[2], f"● {NOVA} high      0", "",
                OWN[6], f"■ Bolt 3 max{' ' * 24}0", OWN[8], "",
                OWN[10], f"■ Crux 2[ medium{' ' * 20}0"])

if __name__ == "__main__":
    unittest.main()
