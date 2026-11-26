"""A seat saved with no reviewers lands tasks and its own PRs on their checks, with no reviewer.

Black-box against AK_BIN, fakeadapter's failing reviewer and a bare GitHub origin, on a project
whose review_rounds is 3 so only the seat's empty reviewers list turns review off.
"""

import contextlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

FAILING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}


class SeatWithNoReviewer(unittest.TestCase):
    def staged(self, *, workers=("opus",), work="work", planned=True):
        home = Home()
        self.addCleanup(home.close)
        home.env.update(AK_NOTIFY_SINK=None,
                        AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 16000}))
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       settings={"review_rounds": 3})
        rules = "---\ntests: test ! -f bad.txt\nhealth: none\nusers: none\nreview_rounds: 3\n---\n# Widgets\n"
        rig = Rig(home, "widgets", files={"AGENTS.md": rules})
        rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        fakes = fakeadapter.install(home, claude=work, codex=FAILING)
        Seat(home, "acme", model="opus", cwd=rig.path, alive=False, planned=planned,
             record={"workers": list(workers), "reviewers": []})
        return home, rig, gh, fakes

    def launch(self, *, workers=("opus",), pr=False, work="work",
               checks=("test -f retry.txt",), files=None, flags=()):
        home, rig, gh, fakes = self.staged(workers=workers, work=work, planned=checks)
        if pr:
            rig.branch("contrib", files or {"retry.txt": "hello\n"})
            args = ("--review-pr", gh.open_pr(rig, "contrib", author="acme"))
        else:
            args = (str(taskfile.write(home, rig.path, done_when=checks)),)
        done = home.ak("run", *args, *flags, timeout=300, env={"AGENTKIT_SESSION": "acme"})
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        return home, rig, fakes, done, directory, state

    def test_a_task_from_a_seat_with_no_reviewer_merges_without_a_reviewer_turn(self):
        home, rig, fakes, done, directory, state = self.launch()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["verdict"], state["merged"]), ("PASS", True))
        self.assertEqual((state["workers"], state["reviewers"], state["reviewer"]),
                         (["opus"], [], None))
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (1, 0))
        self.assertIn("retry.txt", rig.files())
        self.assertIn("no review", (directory / "result.md").read_text().splitlines())
        self.assertIn("no review", home.ak("run", "status", directory.name, "--plain").out)
        with contextlib.closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
            row = db.execute("SELECT no_review, rounds_used FROM runs WHERE run_id=?",
                             (directory.name,)).fetchone()
            self.assertEqual(row, (1, 0))
            self.assertIn(("landing", 0), db.execute(
                "SELECT kind, exit FROM checks WHERE run_id=?", (directory.name,)).fetchall())

    def test_own_pr_from_a_seat_with_no_builder_or_reviewer_merges_without_a_reviewer_turn(self):
        home, rig, gh, fakes = self.staged(workers=())
        task = taskfile.write(home, rig.path, done_when=("test -f retry.txt",))
        refused = home.ak("run", str(task), timeout=60, env={"AGENTKIT_SESSION": "acme"})
        self.assertNotEqual(refused.code, 0)
        self.assertIn("acme has no executor", refused.err)
        self.assertEqual(taskfile.runs(home), [])

        rig.branch("contrib", {"retry.txt": "hello\n"})
        url = gh.open_pr(rig, "contrib", author="acme")
        done = home.ak("run", "--review-pr", url, timeout=300, env={"AGENTKIT_SESSION": "acme"})
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["verdict"], state["merged"], state["review_posted"]),
                         ("PASS", True, False))
        self.assertEqual((state["workers"], state["reviewers"], state["reviewer"]), ([], [], None))
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (0, 0))
        self.assertIn("retry.txt", rig.files())
        self.assertIn("no review", (directory / "result.md").read_text().splitlines())
        with contextlib.closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
            row = db.execute("SELECT no_review, rounds_used FROM runs WHERE run_id=?",
                             (directory.name,)).fetchone()
            self.assertEqual(row, (1, 0))

    def test_failing_checks_stop_after_one_round_with_no_reviewer(self):
        _, _, fakes, done, directory, state = self.launch(checks=("false",))
        self.assertNotEqual(done.code, 0)
        self.assertFalse(state["merged"])
        self.assertEqual(fakes["codex"].n, 0)
        self.assertFalse((directory / "round-2").exists())

        _, _, fakes, done, _, state = self.launch(
            workers=(), pr=True, files={"retry.txt": "hello\n", "bad.txt": "bad\n"},
            flags=("--no-merge",))
        self.assertNotEqual(done.code, 0)
        self.assertEqual((state["state"], state["merged"]), ("fail", False))
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (0, 0))

    def test_a_red_landing_suite_on_an_own_pr_is_fixed_and_landed_without_review(self):
        fix = {"sh": "git rm -q bad.txt", "commit": "remove bad.txt", "hand_in": [["done"]],
               "final": "## Summary\nremoved bad.txt"}
        _, rig, fakes, done, _, state = self.launch(
            workers=(), pr=True, work=fix,
            files={"retry.txt": "hello\n", "bad.txt": "bad\n"})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(state["merged"])
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()], ["fixer"])
        self.assertEqual(fakes["codex"].n, 0)
        self.assertNotIn("bad.txt", rig.files())

    def test_a_followup_run_of_a_seat_with_no_reviewer_lands_on_its_checks(self):
        home = Home()
        self.addCleanup(home.close)
        home.env.update(AK_NOTIFY_SINK=None,
                        AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 16000}))
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       settings={"review_rounds": 3})
        rules = "---\ntests: test ! -f bad.txt\nhealth: none\nusers: none\nreview_rounds: 3\n---\n# Widgets\n"
        rig = Rig(home, "widgets", files={"AGENTS.md": rules})
        rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        GitHub(home).grant(rig.slug, "WRITE")
        release = home.root / "adapters" / "release"
        wait = (f"i=0; while [ ! -f {shlex.quote(str(release))} ] && [ $i -lt 1000 ]; "
                "do sleep 0.1; i=$((i+1)); done")
        fix_work = {"write": {"sturdy.txt": "sturdy\n"}, "commit": "add sturdy.txt",
                    "final": "## Summary\nwrote sturdy.txt", "hand_in": [["done"]]}
        followup_review = {"final": "One more defect.", "hand_in": [
            ["follow-up", "retry.txt:1", "flimsy widget", "it breaks later", "--run",
             "test -f sturdy.txt"], ["done"]]}
        fakes = fakeadapter.install(home, claude=[{"sh": wait, **fakeadapter.WORK}, fix_work],
                                    codex=[followup_review, FAILING])
        Seat(home, "acme", model="opus", cwd=rig.path, alive=False, planned=True,
             record={"workers": ["opus"], "reviewers": ["astra"]})
        task = taskfile.write(home, rig.path, done_when=("test -f retry.txt",))

        def alive(pid):
            if not isinstance(pid, int):
                return False
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return True

        def settle():
            release.write_text("")
            for run_dir in taskfile.runs(home):
                rec = json.loads((run_dir / "run.json").read_text())
                if alive(rec.get("pid")):
                    home.ak("run", "stop", run_dir.name)
        self.addCleanup(settle)

        proc = home.spawn("run", str(task), env={"AGENTKIT_SESSION": "acme"})
        deadline = time.monotonic() + 120
        while fakes["claude"].n < 1 and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(fakes["claude"].n, 1, home.log("spawn-1.err").read_text())
        # The owner unmarks the seat's reviewers while its run is in flight.
        seat_file = home.path / ".agentkit/state/session-acme.json"
        home.write(seat_file.relative_to(home.path),
                   {**json.loads(seat_file.read_text()), "reviewers": []})
        release.write_text("")
        self.assertEqual(proc.wait(300), 0, home.log("spawn-1.err").read_text())

        runs = taskfile.runs(home)
        self.assertEqual(len(runs), 2, runs)
        parent_dir, fix_dir = runs
        parent = json.loads((parent_dir / "run.json").read_text())
        self.assertEqual(parent.get("followup_runs"), [fix_dir.name])

        deadline = time.monotonic() + 300
        fix = {}
        while time.monotonic() < deadline:
            fix = json.loads((fix_dir / "run.json").read_text())
            if fix.get("finished_at") is not None and not alive(fix.get("pid")):
                break
            time.sleep(0.1)
        self.assertEqual((fix.get("verdict"), fix.get("merged")), ("PASS", True), fix)
        self.assertEqual((fix.get("workers"), fix.get("reviewers"), fix.get("reviewer")),
                         (["opus"], [], None))
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()], ["executor", "executor"])
        self.assertEqual(fakes["codex"].n, 1)
        self.assertIn("sturdy.txt", rig.files())
        self.assertIn("no review", (fix_dir / "result.md").read_text().splitlines())
        with contextlib.closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
            row = db.execute("SELECT no_review, rounds_used FROM runs WHERE run_id=?",
                             (fix_dir.name,)).fetchone()
            self.assertEqual(row, (1, 0))


if __name__ == "__main__":
    unittest.main()
