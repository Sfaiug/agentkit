"""A seat is not done while the project it is filed under has a suite that reports no tests to ak.

A round runs a change's tests only where the suite's runner reports each test's seconds, and being
told so at `ak orch project` is not made sure (owner, 16 Nov 2026): a seat filed under a checkout
`suite_times.unreported` names, its plan holding done work and no open line, goes back at every
stop, however many its turn spent, with one line naming that checkout by its path as filed, saying
what its runner must do as `ak orch project` says it, and telling it to write that outcome into its
plan and build it; nothing is kept, so it stops by itself at the first landing whose runner
reports.  An open line in its plan, a time on record for that project, being filed under a project
with times or one `unreported` does not name (with no done line naming a silent one), being filed
under no project -- even with a done line naming the silent project -- and a plan holding nothing
done end the turn as today.
Black-box: hooks/seat-state.sh starting each turn and hooks/orchestrator-stop.sh ending it, beside
the program `AK_BIN` names, in an answer-key Home holding the history's rows and the test-times
record, as tests/test_key_a_session_is_told_its_suite_reports_no_tests.py writes them.
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

WHOLE, PIECES = "bash tests/all.sh", "export AK_SHARD; bash tests/all.sh"
# a checkout's name a shell would split: the line names its path as filed, in no command
SILENT = "silent app"
RUNNER = ("its runner must print `PASS  <file> (<seconds>s)` for each file that passes and take "
          "ak's files AK_ONLY, AK_RAN, AK_FAILED and AK_NOT_THERE")
PROJECTS = {
    SILENT: (WHOLE, [("a", WHOLE, 0)]),
    "pieces": (PIECES, [("b", f"AK_SHARD=1/2 {PIECES}", 1), ("b", f"AK_SHARD=2/2 {PIECES}", 0)]),
    "timed": (WHOLE, [("c", WHOLE, 0)]),
    "fresh": (PIECES, [("d", f"AK_SHARD=1/2 {PIECES}", 0)]),
    "linked": (WHOLE, [("e", WHOLE, 0)]),
}


class NotDone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.state = home.path / ".agentkit" / "state"
        cls.rigs = {}
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, kind TEXT, "
                       "finished_at REAL)")
            db.execute("CREATE TABLE checks (run_id TEXT, round INTEGER, kind TEXT, tree TEXT, "
                       "command TEXT, exit INTEGER, finished_at REAL)")
            for number, (name, (suite, checks)) in enumerate(PROJECTS.items()):
                rig = cls.rigs[name] = Rig(home, name, files={
                    "AGENTS.md": f"---\ntests: {suite}\nhealth: none\nusers: none\n---\n"})
                rig.git("config", "ak.repository", f"{number:012x}")
                for run, command, code in checks:
                    db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, 'task', 1)", (run, name))
                    db.execute("INSERT INTO checks VALUES (?, NULL, 'landing', 'cedar', ?, ?, 2)",
                               (run, command, code))
        # filed by its link in ~/code, where its landings were recorded, while its target differs
        linked = cls.rigs["linked"].path
        target = home.path / "local" / "service"
        target.parent.mkdir()
        linked.rename(target)
        linked.symlink_to(target, target_is_directory=True)
        home.write(".agentkit/state/test-times-000000000002.json", {"tests/test_api.py": 3.0})
        cls.seat = Seat(home, "fix-api", cwd=cls.rigs[SILENT].path, alive=False)
        cls.plan = cls.state / "plan-fix-api.md"
        cls.said = home.root / "transcript.jsonl"
        cls.said.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Done."}]}}) + "\n")

    def setUp(self):
        self.file(self.rigs[SILENT].path)
        self.lines(self.done(self.where(SILENT)))
        self.prompt()

    def file(self, repo):
        record = {**self.seat.record, **({"repo": str(repo)} if repo else {})}
        if not repo:
            record.pop("repo", None)
        self.home.write(".agentkit/state/session-fix-api.json", record)

    def hook(self, script, payload):
        done = self.home.run("bash", str(ROOT / "hooks" / script), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def prompt(self):
        """The owner's prompt starts a turn, as the harness's UserPromptSubmit hook says."""
        self.hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go",
                                    "session_id": "conv-fix-api"})

    def stop(self):
        """The reason the turn's end is sent back with, or "" where it stands."""
        out = self.hook("orchestrator-stop.sh", {"hook_event_name": "Stop",
                                                 "session_id": "conv-fix-api",
                                                 "transcript_path": str(self.said)})
        return json.loads(out)["reason"] if out.strip() else ""

    def where(self, name):
        rig = self.rigs[name]
        return f"{rig.path.resolve()}#{rig.head()[:12]}"

    def back(self, name):
        return (f"The suite of {self.rigs[name].path} reports no tests to ak: {RUNNER}. "
                "Write that outcome into your plan and build it.")

    def lines(self, *lines):
        self.plan.write_text("".join(f"{line}\n" for line in lines))

    def done(self, where):
        return (f"- [x] the api answers · check: `test -f api.py` · {where} · written "
                "2026-11-18 10:00 · done 0123456789ab")

    def test_a_done_plan_on_a_silent_suite_goes_back_at_every_stop(self):
        # a turn that spent both its blocks on work open, then finished it
        self.lines(f"- [ ] the api answers · check: `false` · {self.where(SILENT)} · written "
                   "2026-11-18 10:00")
        for _ in range(2):
            self.assertNotIn(self.stop(), ("", self.back(SILENT)))
        self.lines(self.done(self.where("timed")), self.done(self.where(SILENT)))
        for _ in range(3):
            self.assertEqual(self.stop(), self.back(SILENT))
        self.prompt()
        self.assertEqual(self.stop(), self.back(SILENT))   # nothing kept: the next turn goes back
        self.assertFalse((self.state / "notify-fix-api.json").exists())
        # `ak orch project` files the path and says the same of the runner, linked checkouts too
        for name in (SILENT, "pieces", "linked"):
            with self.subTest(name):
                told = self.home.ak("orch", "project", "fix-api", str(self.rigs[name].path),
                                    env={"COLUMNS": "250"})
                self.assertEqual(told.code, 0, told.err)
                self.assertTrue(" ".join(told.out.splitlines()[2:]).endswith(f": {RUNNER}"),
                                told.out)
                self.prompt()
                self.assertEqual(self.stop(), self.back(name))

    def test_an_open_line_in_its_plan_ends_it(self):
        silent = self.rigs[SILENT]
        run = self.home.write(".agentkit/runs/20261118-1000-fix-runner/run.json", {
            "run_id": "20261118-1000-fix-runner", "launched_session": "fix-api",
            "state": "running", "repo": str(silent.path), "followup": {"check": "false"}})
        self.addCleanup(run.unlink)
        for suffix in (" · deferred", ""):
            with self.subTest(deferred=bool(suffix)):
                self.prompt()
                self.lines(self.done(self.where(SILENT)),
                           f"- [ ] its runner reports · check: `false` · {self.where(SILENT)}"
                           f"{suffix} · written 2026-11-18 10:00")
                self.assertEqual(self.stop(), "")

    def test_a_time_on_record_for_that_project_ends_it(self):
        self.assertEqual(self.stop(), self.back(SILENT))
        times = self.home.write(".agentkit/state/test-times-000000000000.json",
                                {"tests/test_api.py": 1.0})
        self.addCleanup(times.unlink)
        self.assertEqual(self.stop(), "")

    def test_filed_elsewhere_or_under_no_project(self):
        for name in ("timed", "fresh"):
            with self.subTest(name=name, done=SILENT):
                self.file(self.rigs[name].path)
                self.prompt()
                self.assertEqual(self.stop(), self.back(SILENT))
            with self.subTest(name=name, done=name):
                self.lines(self.done(self.where(name)))
                self.prompt()
                self.assertEqual(self.stop(), "")
                self.lines(self.done(self.where(SILENT)))
        self.file(None)
        self.prompt()
        self.assertEqual(self.stop(), "")

    def test_no_done_line_ends_it(self):
        self.plan.unlink(missing_ok=True)
        self.assertEqual(self.stop(), "")
        for text in ("", "# Plan\n"):
            with self.subTest(text=text):
                self.prompt()
                self.plan.write_text(text)
                self.assertEqual(self.stop(), "")


if __name__ == "__main__":
    unittest.main()
