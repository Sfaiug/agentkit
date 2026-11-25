"""`ak models` prints under its boards a line on the team now and a table a role of `own`, as
`--json` gives it (tests/test_key_models_json_own_rows.py): the team now's tasks, those that went
live and per task live the hours they spent and of them waiting; then each role's rows in
`own`'s order, those in use marked, each with its tasks, the share that went live and per task
live every hour its tasks spent.  A row of fewer than 20 tasks shows its tasks alone, one with
none live no hours.  A model is named as every screen names it at its effort, plain whatever its
label holds, by the name its runs kept once no longer configured or where its label drawn plain
is empty.  All three tables print, a history of one role's former model alone too; under 60
cells a row's numbers fold onto an indented second line, no line passing the edge and no word
that fits cut.

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
MODELS = {"nova": {"harness": "claude", "label": "Acme Nova Seven Extended Thinking Preview"},
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
NOVA = "Acme Nova Seven Extended Thinking Preview"
HEAD = "tasks  went live  per task live"
# The team now: the first two teams, 23 of 44 live, 121 hours, 44 of them waiting
TEAM = ["Your team now: 23 of 44 tasks went live,", "5.3 h per task live, 1.9 h of it waiting"]
OWN = [" ".join(TEAM), "",
       f"ORCHESTRATOR{' ' * 38}{HEAD}",
       f"● {NOVA} high     24        75%          3.7 h",
       f"○ {NOVA}          20        25%         11.0 h",
       "",
       f"BUILDER{' ' * 43}{HEAD}",
       f"■ Bolt 3 max{' ' * 41}44        52%          5.3 h",
       f"□ gale high{' ' * 42}19",
       "",
       f"REVIEWER{' ' * 42}{HEAD}",
       f"■ Crux 2[ medium{' ' * 37}44        52%          5.3 h",
       f"□ echo medium{' ' * 40}30         0%"]
# Under 60 cells each row's numbers on its second line, its name wrapped at words where wider
FOLDED = {55: [*TEAM, "", "ORCHESTRATOR", f"  {HEAD}",
               f"● {NOVA} high", "     24        75%          3.7 h",
               f"○ {NOVA}", "     20        25%         11.0 h"],
          40: [*TEAM, "", "ORCHESTRATOR", f"  {HEAD}",
               "● Acme Nova Seven Extended Thinking", "  Preview high",
               "     24        75%          3.7 h",
               "○ Acme Nova Seven Extended Thinking", "  Preview",
               "     20        25%         11.0 h"]}
ROLES = ["", "BUILDER", f"  {HEAD}", "■ Bolt 3 max", "     44        52%          5.3 h",
         "□ gale high", "     19", "", "REVIEWER", f"  {HEAD}", "■ Crux 2[ medium",
         "     44        52%          5.3 h", "□ echo medium", "     30         0%"]


def home_of(teams):
    """A Home of MODELS, the team now [defaults], whose history holds `teams`' tasks."""
    home = Home()
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS, orchestrator="nova", workers=["bolt"], reviewers=["crux"])
    home.write(".agentkit/state/boards.json", boards())
    runs = [run(f"fix-{name}-{n}", n / 24, **fields, **({} if n < live else FAILED))
            for name, tasks, live, fields in teams for n in range(tasks)]
    history(home, runs, [(row["run_id"], 1, "medium") for row in runs])
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

    def test_the_team_now_then_each_role_s_rows_with_their_numbers(self):
        self.assertEqual(self.own(100), OWN)

    def test_under_60_cells_a_row_s_numbers_fold_onto_its_second_line_inside_the_edge(self):
        for columns, folded in FOLDED.items():
            self.assertEqual(self.own(columns), [*folded, *ROLES], columns)

    def test_a_history_of_a_former_builder_alone_prints_all_three_tables(self):
        with home_of(TEAMS[2:3]) as home:
            self.assertEqual(self.own(100, home), [
                "Your team now has no task yet", "",
                OWN[2], f"● {NOVA} high      0", "",
                OWN[6], f"■ Bolt 3 max{' ' * 42}0", OWN[8], "",
                OWN[10], f"■ Crux 2[ medium{' ' * 38}0"])


if __name__ == "__main__":
    unittest.main()
