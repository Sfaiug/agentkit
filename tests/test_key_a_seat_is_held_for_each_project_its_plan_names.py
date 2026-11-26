"""A seat is held at its stop for each silent project a done line of its plan names.

A seat filed under one project can land work in a second, silent one (owner, 26 Nov 2026): after
the checkout the seat is filed under, `stop.untested` asks `suite_times.unreported` of each
checkout a done line of its plan names (`plan.place`), in the plan's order, each asked once, and
sends the turn back with `UNTESTED_LINE` naming the first that reports no tests.  An open line,
a done line whose project `place` refuses (such as the path holding another repository), or a time
on record for the silent project ends the turn.
Black-box: hooks/seat-state.sh and hooks/orchestrator-stop.sh beside `AK_BIN` in an answer-key Home.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.hookdrive import ROOT

WHOLE, SILENT = "bash tests/all.sh", "silent app"
RUNNER = ("its runner must print `PASS  <file> (<seconds>s)` for each file that passes and take "
          "ak's files AK_ONLY, AK_RAN, AK_FAILED and AK_NOT_THERE")
PROJECTS = ("timed", SILENT, "second")


class HeldForEachProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rigs = {}
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, kind TEXT, "
                       "finished_at REAL)")
            db.execute("CREATE TABLE checks (run_id TEXT, round INTEGER, kind TEXT, tree TEXT, "
                       "command TEXT, exit INTEGER, finished_at REAL)")
            for number, name in enumerate(PROJECTS):
                rig = cls.rigs[name] = Rig(home, name, files={
                    "README": name,
                    "AGENTS.md": f"---\ntests: {WHOLE}\nhealth: none\nusers: none\n---\n"})
                rig.git("config", "ak.repository", f"{number:012x}")
                db.execute("INSERT INTO runs VALUES (?, ?, 'task', 1)", (f"r{number}", name))
                db.execute("INSERT INTO checks VALUES (?, NULL, 'landing', 'cedar', ?, 0, 2)",
                           (f"r{number}", WHOLE))
        home.write(".agentkit/state/test-times-000000000000.json", {"tests/test_api.py": 3.0})
        timed = cls.rigs["timed"].path
        Seat(home, "fix-api", cwd=timed, record={"repo": str(timed)}, alive=False)
        cls.plan = home.path / ".agentkit" / "state" / "plan-fix-api.md"
        cls.said = home.root / "transcript.jsonl"
        cls.said.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Done."}]}}) + "\n")

    def setUp(self):
        self.lines(self.done(self.where(SILENT)))
        self.hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go",
                                    "session_id": "conv-fix-api"})

    def hook(self, script, payload):
        done = self.home.run("bash", str(ROOT / "hooks" / script), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def stop(self):
        out = self.hook("orchestrator-stop.sh", {"hook_event_name": "Stop",
                                                 "session_id": "conv-fix-api",
                                                 "transcript_path": str(self.said)})
        return json.loads(out)["reason"] if out.strip() else ""

    def where(self, name, root=None):
        return f"~/code/{name}#{(root or self.rigs[name].head())[:12]}"

    def back(self, name):
        return (f"The suite of {self.rigs[name].path} reports no tests to ak: {RUNNER}. "
                "Write that outcome into your plan and build it.")

    def lines(self, *lines):
        self.plan.write_text("".join(f"{line}\n" for line in lines))

    def done(self, where):
        return (f"- [x] the api answers · check: `test -f api.py` · {where} · written "
                "2026-11-26 10:00 · done 0123456789ab")

    def test_a_done_line_on_a_silent_checkout_goes_back_in_plan_order(self):
        self.lines(self.done(self.where("timed")), self.done(self.where(SILENT)))
        self.assertEqual(self.stop(), self.back(SILENT))
        self.lines(self.done(self.where("second")), self.done(self.where(SILENT)))
        self.assertEqual(self.stop(), self.back("second"))

    def test_an_open_line_on_the_silent_checkout_ends_it(self):
        run = self.home.write(".agentkit/runs/20261126-1000-fix-runner/run.json", {
            "run_id": "20261126-1000-fix-runner", "launched_session": "fix-api",
            "state": "running", "repo": str(self.rigs[SILENT].path),
            "followup": {"check": "false"}})
        self.addCleanup(run.unlink)
        self.lines(f"- [ ] its runner reports · check: `false` · {self.where(SILENT)} · written "
                   "2026-11-26 10:00")
        self.assertEqual(self.stop(), "")

    def test_a_done_line_whose_project_place_refuses_ends_it(self):
        self.lines(self.done(self.where(SILENT, root=self.rigs["timed"].head())))
        self.assertEqual(self.stop(), "")

    def test_a_time_on_record_for_the_silent_project_ends_it(self):
        self.assertEqual(self.stop(), self.back(SILENT))
        times = self.home.write(".agentkit/state/test-times-000000000001.json",
                                {"tests/test_api.py": 1.0})
        self.addCleanup(times.unlink)
        self.assertEqual(self.stop(), "")


if __name__ == "__main__":
    unittest.main()
