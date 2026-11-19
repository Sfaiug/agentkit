"""A run's row in history names the effort its orchestrator ran at.

A run's `runs` row names its `orchestrator`, the model the launching seat's record names, and
keeps `orchestrator_effort`: the effort the run's receipt holds for that model orchestrating,
which is the seat's own where the seat runs its model at one the model's [models.*] entry does
not name.  So the tasks a model launched at one effort are told from those it launched at
another.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, a seat from akseat.py and a scripted
harness from fakeadapter.py, judged by the run's row in history.db once it has ended.
"""

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

# The quickest ending: the executor's first turn hands in blocked, with nothing to review.
BLOCKED = {"final": "Blocked.", "hand_in": [["blocked", "cannot be done as written"]]}
# The Home's notify sink marks every run a test suite's, which ak never records: this one goes
# without it, as the seat's, and with no webhook configured nothing is posted anywhere.
FROM_THE_SEAT = {"AK_NOTIFY_SINK": None, "AGENTKIT_SESSION": "acme"}


class ARunRecordsItsOrchestratorsEffort(unittest.TestCase):
    def test_the_row_names_the_effort_the_seat_ran_its_orchestrator_at(self):
        with Home() as home:
            rig = Rig(home, "widgets")
            akconfig.write(home, {"opus": {"effort": "high"}, "astra": {}})
            fakeadapter.install(home, claude=BLOCKED, codex="pass")
            Seat(home, "acme", cwd=rig.path, planned=True, alive=False,
                 record={"efforts": {"opus": {"effort": "max"}}})
            task = taskfile.write(home, rig.path, "Add retry file")
            done = home.ak("run", str(task), env=FROM_THE_SEAT, timeout=300)
            run_id = taskfile.only_run(home).name
            with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
                row = db.execute("SELECT final_state, orchestrator, orchestrator_effort FROM runs "
                                 "WHERE run_id=?", (run_id,)).fetchone()
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(row, ("blocked", "opus", "max"))


if __name__ == "__main__":
    unittest.main()
