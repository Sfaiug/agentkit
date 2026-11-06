"""Run kinds survive cleanup, and only seat tasks size the next task.

Black-box: AK_BIN runs a seat's task and its follow-up, reviews the seat's own PR,
and migrates an older history.db.  The durable rows are read directly with sqlite3.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_history_db import DATABASE, ORIGINAL, columns, read

FOLLOW_UP = {"final": "One for later.", "hand_in": [
    ["follow-up", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
     "test ! -f retry.txt || { wc -l < retry.txt; false; }"], ["done"]]}


def state(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def ended(run_dir, bound=180):
    # A detached run's final log line follows its history write.
    deadline = time.monotonic() + bound
    while time.monotonic() < deadline:
        log = run_dir / "log.txt"
        if log.exists() and log.read_text().rstrip().endswith(f" -> {run_dir / 'result.md'}"):
            return
        time.sleep(0.2)
    raise AssertionError(f"{run_dir.name} never ended: {state(run_dir).get('state')}")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TaskAndFollowUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # The owner's runs have no suite notify sink, so they leave history rows.
        cls.home.env.pop("AK_NOTIFY_SINK")
        cls.rig = Rig(cls.home, "widgets")
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        # Changing the failure's output avoids the stop for identical failures before round 3.
        attempt = {"sh": "printf 'attempt\\n' >> retry.txt", "commit": "try the follow-up",
                   "final": "Tried.", "hand_in": [["done"]]}
        fakeadapter.install(cls.home, claude=["work", attempt], codex=[FOLLOW_UP, "fail"])
        Seat(cls.home, "acme", cwd=cls.rig.path, record={"workers": ["opus", "astra"]},
             planned=True)
        task = taskfile.write(cls.home, cls.rig.path)
        cls.done = cls.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=300)
        if cls.done.code:
            raise AssertionError(cls.done.out + cls.done.err)
        cls.task = next(run for run in taskfile.runs(cls.home) if not state(run).get("followup"))
        cls.fix = cls.home.path / ".agentkit/runs" / state(cls.task)["followup_runs"][0]
        ended(cls.fix)
        cls.rows = {row["run_id"]: row for row in read(cls.home, "SELECT * FROM runs")}
        cls.status = cls.home.ak("run", "status", "--history")

    def test_the_task_and_its_fix_keep_their_launch_kind(self):
        self.assertTrue(state(self.task)["merged"])
        self.assertEqual(state(self.fix)["followup"]["run"], self.task.name)
        self.assertEqual(self.rows[self.task.name]["kind"], "task")
        self.assertEqual(self.rows[self.fix.name]["kind"], "follow-up")
        self.assertIsNone(state(self.fix).get("plan_line"))
        self.assertIsNone(self.rows[self.fix.name]["plan_line"])

    def test_the_size_line_reads_the_task_s_one_round_and_not_the_fix_s_three(self):
        task, fix = self.rows[self.task.name], self.rows[self.fix.name]
        self.assertEqual((task["final_state"], task["rounds_used"]), ("pass", 1))
        self.assertEqual((fix["final_state"], fix["rounds_used"]), ("fail", 3),
                         (self.fix / "result.md").read_text())
        self.assertEqual(self.status.code, 0, self.status.out + self.status.err)
        self.assertIn("widgets: last 20 tasks: median 1 rounds", self.status.out)


class SeatPr(unittest.TestCase):
    def test_a_review_learns_its_seat_s_ownership_after_the_row_started(self):
        with Home() as home:
            home.env.pop("AK_NOTIFY_SINK")
            rig = Rig(home, "widgets", files={"AGENTS.md": "---\ntests: test -f contrib.txt\nusers: none\n---\n"})
            gh = GitHub(home)
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="pass", codex="pass")
            Seat(home, "acme", cwd=rig.path, alive=False,
                 record={"workers": ["opus", "astra"]}, planned=True)
            rig.branch("contrib", {"contrib.txt": "c\n"})
            url = gh.open_pr(rig, "contrib")
            done = home.ak("run", "--review-pr", url, env={"AGENTKIT_SESSION": "acme"},
                           cwd=rig.path, timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            run_dir = taskfile.only_run(home)
            self.assertTrue(state(run_dir)["own_pr"])
            self.assertTrue(state(run_dir)["merged"])
            self.assertIsNone(state(run_dir).get("plan_line"))
            self.assertIsNone(read(home, "SELECT plan_line FROM runs")[0]["plan_line"])
            self.assertEqual(read(home, "SELECT run_id, kind FROM runs"),
                             [{"run_id": run_dir.name, "kind": "seat PR"}])


class StaleMergedColumn(unittest.TestCase):
    def test_migration_drops_the_unused_column_and_keeps_the_old_row_unknown(self):
        with Home() as home:
            db = sqlite3.connect(home.path / DATABASE)
            try:
                db.execute("CREATE TABLE runs (%s, merged INTEGER)" % ", ".join(map(" ".join, ORIGINAL)))
                db.execute("INSERT INTO runs (run_id, repo, rounds_used, final_state, finished_at) "
                           "VALUES ('old-task', 'acme', 2, 'pass', ?)", (time.time(),))
                db.commit()
            finally:
                db.close()
            done = home.ak("run", "status", "--history")
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertNotIn("merged", columns(home, "runs"))
            self.assertEqual(read(home, "SELECT run_id, rounds_used, kind FROM runs"),
                             [{"run_id": "old-task", "rounds_used": 2, "kind": None}])
            self.assertIn("acme: last 20 tasks: median 2 rounds", done.out)


if __name__ == "__main__":
    unittest.main()
