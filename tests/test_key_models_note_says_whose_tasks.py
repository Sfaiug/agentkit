"""The note under `ak models`'s tables says which tasks each table counts: a role's rows count
only the tasks the models in use now did the other two roles in, at no other effort, so a model
that built hundreds shows few under an orchestrator that wrote few, and the page says why.

Black-box: the program `AK_BIN` names over tests/test_key_models_own_tables.py's history; judged
by its output.  Fails against /bin/false.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akboards import ENV
from test_key_models_own_tables import NOTE, TASKS, TEAMS, WIDE, home_of


class NoteSaysWhoseTasks(unittest.TestCase):
    def test_the_note_opens_with_which_tasks_a_table_counts(self):
        with home_of(TEAMS) as home:
            done = home.ak("models", env={**ENV, "COLUMNS": str(WIDE)})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[-len(NOTE)], TASKS)


if __name__ == "__main__":
    unittest.main()
