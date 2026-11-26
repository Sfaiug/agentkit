"""A seat is held at its stop for each silent project a merged run of its own names.

A seat whose plan names one project can merge runs into a second, silent one (owner, 26 Nov
2026): after the checkout the seat is filed under and those its plan's done lines name,
`stop.untested` asks `suite_times.unreported` of the checkout (`repo`) of each run of the seat's
own whose record holds it `merged`, in run-id order, and sends the turn back with `UNTESTED_LINE`
naming the first that reports no tests.  The same run not merged, or launched before the seat was
made (another seat's that had its name), or a time on record for the silent project ends the turn.
Black-box: hooks/seat-state.sh and hooks/orchestrator-stop.sh beside `AK_BIN` in an answer-key Home.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.hookdrive import ROOT

WHOLE, SILENT = "bash tests/all.sh", "silent app"
RUNNER = ("its runner must print `PASS  <file> (<seconds>s)` for each file that passes and take "
          "ak's files AK_ONLY, AK_RAN, AK_FAILED and AK_NOT_THERE")
PROJECTS = ("timed", SILENT)
RUN = "20261126-1000-fix-runner"


class HeldForEachMergedProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rigs = {}
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, kind TEXT, finished_at REAL)")
            db.execute("CREATE TABLE checks (run_id TEXT, round INTEGER, kind TEXT, tree TEXT, "
                       "command TEXT, exit INTEGER, finished_at REAL)")
            for number, name in enumerate(PROJECTS):
                rig = cls.rigs[name] = Rig(home, name, files={
                    "README": name, "AGENTS.md": f"---\ntests: {WHOLE}\nhealth: none\nusers: none\n---\n"})
                rig.git("config", "ak.repository", f"{number:012x}")
                db.execute("INSERT INTO runs VALUES (?, ?, 'task', 1)", (f"r{number}", name))
                db.execute("INSERT INTO checks VALUES (?, NULL, 'landing', 'cedar', ?, 0, 2)", (f"r{number}", WHOLE))
        home.write(".agentkit/state/test-times-000000000000.json", {"tests/test_api.py": 3.0})
        timed = cls.rigs["timed"].path
        cls.created = Seat(home, "fix-api", cwd=timed, record={"repo": str(timed)}, alive=False).record["created"]
        home.write(".agentkit/state/plan-fix-api.md",
                   f"- [x] the api answers · check: `test -f api.py` · ~/code/timed#"
                   f"{cls.rigs['timed'].head()[:12]} · written 2026-11-26 10:00 · done 0123456789ab\n")
        cls.said = home.root / "transcript.jsonl"
        cls.said.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Done."}]}}) + "\n")

    def setUp(self):
        self.hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go",
                                    "session_id": "conv-fix-api"})

    def hook(self, script, payload):
        done = self.home.run("bash", str(ROOT / "hooks" / script), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def stop(self):
        out = self.hook("orchestrator-stop.sh", {"hook_event_name": "Stop", "session_id": "conv-fix-api",
                                                 "transcript_path": str(self.said)})
        return json.loads(out)["reason"] if out.strip() else ""

    def run_in_silent(self, **fields):
        run = self.home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "launched_session": "fix-api", "state": "pass", "verdict": "PASS",
            "merged": True, "repo": str(self.rigs[SILENT].path), "started_at": time.time(), **fields})
        self.addCleanup(run.unlink, missing_ok=True)

    def test_a_merged_run_in_a_silent_project_goes_back_naming_it(self):
        self.assertEqual(self.stop(), "")
        self.run_in_silent()
        self.assertEqual(self.stop(), (f"The suite of {self.rigs[SILENT].path} reports no tests to "
                                       f"ak: {RUNNER}. Write that outcome into your plan and build it."))

    def test_the_run_not_merged_ends_it(self):
        self.run_in_silent(merged=False)
        self.assertEqual(self.stop(), "")

    def test_the_run_launched_before_the_seat_was_made_ends_it(self):
        for launch in ({"started_at": self.created - 60},
                       {"queued_at": self.created - 60, "started_at": self.created + 60}):
            with self.subTest(**launch):
                self.run_in_silent(**launch)
                self.assertEqual(self.stop(), "")

    def test_a_time_on_record_for_the_silent_project_ends_it(self):
        self.run_in_silent()
        times = self.home.write(".agentkit/state/test-times-000000000001.json", {"tests/test_api.py": 1.0})
        self.addCleanup(times.unlink)
        self.assertEqual(self.stop(), "")


if __name__ == "__main__":
    unittest.main()
