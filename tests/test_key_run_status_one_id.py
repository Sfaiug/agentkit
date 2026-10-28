"""`ak run status <id>` shows one run and marks its ending looked at.

An ending is news until somebody has looked at it: a failed run reads `needs you` in the
listing until it is opened by id, and from then on it reads `done`, so one failure never asks
twice.  The look itself still shows the run as it found it, and a second look keeps the first
one's mark.  An error whose retry is scheduled is still working, so looking at it cancels
nothing, and an id with no run is refused before anything is shown.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on run records written under
HOME.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat

LOOKED = "recovery_acknowledged_at"


class OneRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.runs = cls.home.path / ".agentkit/runs"
        # an error's retry is the tick's only while the seat that launched it is still there
        Seat(cls.home, "acme", alive=False)
        cls.failed = cls.ended("fix-api", state="fail", verdict="FAIL")
        cls.passed = cls.ended("add-beta", state="pass", verdict="PASS", no_merge=True)
        cls.retrying = cls.ended("ship-gamma", state="error", error="git fetch failed",
                                 error_retry_at=time.time() + 3600, launched_session="acme")

    @classmethod
    def ended(cls, slug, **fields):
        run_id = f"20261020-0900-{slug}"
        finished = time.time() - 600
        cls.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": slug, "executor": "opus", "reviewer": "astra",
            "rounds": 3, "started_at": finished - 1800, "finished_at": finished, **fields})
        return run_id

    def status(self, *args):
        done = self.home.ak("run", "status", *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def record(self, run_id):
        return json.loads((self.runs / run_id / "run.json").read_text())

    def row(self, out, run_id):
        rows = [line for line in out.splitlines() if line.startswith(run_id)]
        self.assertEqual(len(rows), 1, out)
        return rows[0]

    def test_a_failed_run_looked_at_by_id_is_shown_as_found_and_then_listed_done(self):
        self.assertIn("! needs you", self.row(self.status(), self.failed))
        self.assertNotIn(LOOKED, self.record(self.failed))
        out = self.status(self.failed)
        self.assertIn("! needs you", self.row(out, self.failed))
        folder = self.runs / self.failed
        for line in (f"  result: {folder}/result.md", f"  record: {folder}/run.json"):
            self.assertIn(line, out.splitlines())
        self.assertIsInstance(self.record(self.failed)[LOOKED], (int, float))
        self.assertIn("✓ done", self.row(self.status(), self.failed))

    def test_a_passed_run_is_marked_by_its_first_look_even_as_json(self):
        self.assertNotIn(LOOKED, self.record(self.passed))
        shown = json.loads(self.status(self.passed, "--json"))
        self.assertEqual([entry["run_id"] for entry in shown], [self.passed])
        first = self.record(self.passed)[LOOKED]
        self.status(self.passed)
        self.assertEqual(self.record(self.passed)[LOOKED], first)

    def test_looking_at_a_scheduled_retry_cancels_nothing(self):
        before = self.record(self.retrying)["error_retry_at"]
        self.assertIn("● working", self.row(self.status(self.retrying), self.retrying))
        after = self.record(self.retrying)
        self.assertNotIn(LOOKED, after)
        self.assertEqual(after.get("error_retry_at"), before)

    def test_a_look_that_marks_nothing_shows_a_run_whose_directory_it_cannot_list(self):
        # looked at and swept already: neither the look nor the reap has anything to write
        run_id = self.ended("seen-delta", state="fail", verdict="FAIL", tree_stopped=[None, None],
                            **{LOOKED: time.time()})
        folder = self.runs / run_id
        folder.chmod(0o311)
        self.addCleanup(folder.chmod, 0o755)
        out = self.status(run_id)
        row = self.row(out, run_id)
        for shown in ("✓ done", "opus/astra", "round 0/3"):
            self.assertIn(shown, row)

    def test_an_id_with_no_run_is_refused_before_anything_is_shown(self):
        done = self.home.ak("run", "status", "20261020-0900-nosuch")
        self.assertEqual((done.code, done.out), (2, ""))
        self.assertEqual(done.err, f"ak run: no such run: 20261020-0900-nosuch "
                                   f"(looked in {self.runs})\n")


if __name__ == "__main__":
    unittest.main()
