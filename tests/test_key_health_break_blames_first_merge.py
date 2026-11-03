"""Health blames the first failing merge after the latest pass; commit checks blame none.

Black-box through AK_BIN, with the Home, project, GitHub, seats and sink health_pass uses.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink
from test_key_history_db import ORIGINAL


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class HealthBreakBlamesFirstMerge(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        config = self.home.path / ".agentkit/config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        self.rig = Rig(self.home, "app")
        self.gh = GitHub(self.home)
        self.seats = {}
        self.db = self.home.path / ".agentkit/history.db"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE runs (%s, broke_after_merge TEXT)" %
                       ", ".join(map(" ".join, ORIGINAL)))

    def merge(self, name, number, age, command):
        sha = self.rig.commit({"AGENTS.md": f"---\nhealth: {command}\n---\n"}, name)
        self.seats[name] = Seat(self.home, name, cwd=self.rig.path)
        now = time.time()
        path = self.home.write(f".agentkit/runs/{name}/run.json", {
            "run_id": name, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - age, "started_at": now - age - 600,
            "repo": str(self.rig.path), "pr": f"https://github.com/acme/app/pull/{number}",
            "merge_sha": sha, "health": {"command": command}, "launched_session": name,
            "handed_back": now - age, "reported": True})
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO runs (run_id, repo, final_state, broke_after_merge) "
                       "VALUES (?, 'app', 'pass', '')", (name,))
        return path, sha

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.sink.pages(), [])

    def blame(self):
        with closing(sqlite3.connect(self.db)) as db:
            return dict(db.execute("SELECT run_id, broke_after_merge FROM runs"))

    def expire(self, *paths):
        for path in paths:
            record = json.loads(path.read_text())
            self.assertEqual(record["health"]["output"], "down")
            record["finished_at"] -= 3 * 3600
            path.write_text(json.dumps(record))

    def test_the_first_of_two_failing_merges_is_told_and_blamed_once(self):
        first, _ = self.merge("acme-one", 1, 1200, "echo down; exit 1")
        second, _ = self.merge("acme-two", 2, 600, "echo down; exit 1")
        self.tick()
        self.assertEqual([seat.typed() for seat in self.seats.values()], ["", ""])
        self.expire(first, second)
        self.tick()
        lines = self.seats["acme-one"].lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("health: echo down; exit 1 failed on main after this merge.", lines[0])
        self.assertIn("https://github.com/acme/app/pull/1", lines[0])
        self.assertEqual(self.seats["acme-two"].typed(), "")
        self.assertEqual(self.blame(), {"acme-one": "health", "acme-two": ""})
        self.tick()
        self.assertEqual(self.seats["acme-one"].lines(), lines)
        self.assertEqual(self.seats["acme-two"].typed(), "")

    def test_failing_commit_checks_with_passing_health_tell_and_blame_nobody(self):
        path, sha = self.merge("acme-one", 1, 600, "exit 0")
        self.gh.check(sha, "nightly", conclusion="failure")
        self.tick()
        self.assertIsInstance(json.loads(path.read_text()).get("live_at"), (int, float))
        self.assertEqual(self.seats["acme-one"].typed(), "")
        self.assertEqual(self.blame(), {"acme-one": ""})
        self.assertFalse(any("/check-runs" in arg for call in self.home.calls("gh")
                             for arg in call))


if __name__ == "__main__":
    unittest.main()
