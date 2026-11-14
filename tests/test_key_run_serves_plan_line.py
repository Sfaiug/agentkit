"""A seat's task names the open plan line it serves, before the run starts work.

Black-box: AK_BIN launches tasks from an akseat seat. Host readings hold them at
admission so both run.json and history.db must already name the line. A check
replacement keeps that link; a task running no open line's check names none.
"""

from contextlib import closing
import json
import re
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from test_key_history_db import DATABASE, ORIGINAL, read

SEAT = "fix-api"
READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 2,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}


class RunServesPlanLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env.pop("AK_NOTIFY_SINK")
        self.home.env.pop("AK_MAX_RUNS")
        self.home.env["AK_HOST_READINGS"] = json.dumps(READINGS)
        self.rig = Rig(self.home, "acme")
        akconfig.write(self.home, ["opus", "astra"], settings={"max_load": 1})
        fakeadapter.install(self.home, claude="work", codex="pass")
        Seat(self.home, SEAT, cwd=self.rig.path, alive=False,
             record={"repo": str(self.rig.path), "workers": ["opus", "astra"]})
        for part in ("api", "web"):
            self.ak("plan", "add", f"acme {part}", "--check", f"test -f {part}.txt")

    def ak(self, *args, seat=SEAT):
        done = self.home.ak(*args, cwd=self.rig.path,
                            env={"AGENTKIT_SESSION": seat, "COLUMNS": "500"})
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def line(self, number):
        listed = self.ak("plan").splitlines()[number - 1]
        found = re.search(r"- \[[ x]\] (.+?) · check: .* · written "
                          r"(\d{4}-\d\d-\d\d \d\d:\d\d)", listed)
        self.assertIsNotNone(found, listed)
        return f"{found[1]} · written {found[2]}"

    def launch(self, *commands, seat=SEAT):
        task = taskfile.write(self.home, self.rig.path, "Build acme", done_when=commands)
        self.ak("run", str(task), "--no-merge", "--bg", seat=seat)
        directory = taskfile.only_run(self.home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual(state["state"], "queued")
        rows = read(self.home, "SELECT run_id, plan_line FROM runs")
        self.assertEqual(rows, [{"run_id": directory.name, "plan_line": state.get("plan_line")}])
        return directory, state.get("plan_line")

    def test_a_matching_check_names_the_line_and_a_replacement_keeps_the_link(self):
        expected = self.line(2)
        directory, linked = self.launch("test -f web.txt")
        self.assertEqual(linked, expected)
        self.ak("plan", "check", "2", "test -f web2.txt")
        self.assertEqual(self.line(2), expected)
        self.assertEqual(json.loads((directory / "run.json").read_text())["plan_line"], expected)
        self.assertEqual(read(self.home, "SELECT plan_line FROM runs"), [{"plan_line": expected}])

    def test_runs_of_spaces_are_folded_when_checks_are_compared(self):
        _, linked = self.launch("test    -f   web.txt")
        self.assertEqual(linked, self.line(2))

    def test_the_first_matching_plan_line_wins_whichever_command_comes_first(self):
        _, linked = self.launch("test -f web.txt", "test -f api.txt")
        self.assertEqual(linked, self.line(1))

    def test_an_unmatched_task_with_two_open_lines_launches_without_a_link(self):
        _, linked = self.launch("test -f notes.txt")
        self.assertIsNone(linked)

    def test_an_unmatched_task_names_no_line_though_one_line_is_open(self):
        self.rig.commit({"api.txt": "api\n"}, "ship api")
        self.assertIn("- [x] acme api", self.ak("plan"))
        _, linked = self.launch("test -f notes.txt")
        self.assertIsNone(linked)

    def test_a_launch_outside_a_seat_names_no_line(self):
        _, linked = self.launch("test -f web.txt", seat=None)
        self.assertIsNone(linked)

    def test_an_older_database_gains_the_column_without_linking_old_runs(self):
        with closing(sqlite3.connect(self.home.path / DATABASE)) as db, db:
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
            db.execute("INSERT INTO runs (run_id, repo, final_state) "
                       "VALUES ('old-task', 'acme', 'pass')")
        self.ak("run", "status", "--history")
        self.assertEqual(read(self.home, "SELECT run_id, plan_line FROM runs"),
                         [{"run_id": "old-task", "plan_line": None}])


if __name__ == "__main__":
    unittest.main()
