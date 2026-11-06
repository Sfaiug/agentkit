"""Review off lands on checks, with no reviewer; one round still requires its verdict.

Black-box against AK_BIN, fakeadapter's failing reviewer and a bare GitHub origin.
"""

import contextlib
import json
from pathlib import Path
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


class ReviewOff(unittest.TestCase):
    def test_invalid_round_counts_name_the_zero_floor(self):
        with Home() as home:
            task = taskfile.write(home, "none", done_when=("true",))
            for value in (-1, 2.5, True, "no limit"):
                akconfig.write(home, ["opus"], settings={"review_rounds": value})
                done = home.ak("run", str(task), timeout=60)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertEqual(done.err, f"ak run: {home.path / '.agentkit/config.toml'}: review_rounds must be a whole number of at least 0, "
                                 f"the review rounds a change has before it goes back to its orchestrator to split or re-scope (got {value!r})\n")
                self.assertEqual(taskfile.runs(home), [])

    def staged(self, rounds, *, project=False, work="work"):
        home = Home()
        self.addCleanup(home.close)
        home.env.update(AK_NOTIFY_SINK=None,
                        AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 16000}))
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       settings={"review_rounds": 1 - rounds if project else rounds})
        rules = "---\ntests: test ! -f bad.txt\nhealth: none\nusers: none\n"
        rules += f"review_rounds: {rounds}\n" if project else ""
        rig = Rig(home, "widgets", files={"AGENTS.md": rules + "---\n# Widgets\n"})
        rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        fakes = fakeadapter.install(home, claude=work, codex=FAILING)
        return home, rig, gh, fakes

    def launch(self, rounds, *, project=False, pr=False, own=False, work="work",
               checks=("test -f retry.txt",), files=None, flags=()):
        home, rig, gh, fakes = self.staged(rounds, project=project, work=work)
        if pr:
            rig.branch("contrib", files or {"retry.txt": "hello\n"})
            if own:
                Seat(home, "acme", model="opus", cwd=rig.path, alive=False, planned=True)
            args = ("--review-pr", gh.open_pr(rig, "contrib", author="acme" if own else "other-dev"))
        else:
            args = (str(taskfile.write(home, rig.path, done_when=checks)),)
        done = home.ak("run", *args, *flags, timeout=300, env={"AGENTKIT_SESSION": "acme"} if own else {})
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        return home, rig, fakes, done, directory, state

    def test_host_and_project_zero_land_without_a_reviewer_and_one_fails_after_one(self):
        for project in (False, True):
            for rounds in (0, 1):
                with self.subTest(project=project, rounds=rounds):
                    home, rig, fakes, done, directory, state = self.launch(rounds, project=project)
                    self.assertEqual(done.code, rounds, done.out + done.err)
                    self.assertEqual((state["verdict"], state["merged"]),
                                     ("PASS", True) if rounds == 0 else ("FAIL", False))
                    self.assertEqual((state["rounds"], fakes["codex"].n), (rounds, rounds))
                    result = (directory / "result.md").read_text().splitlines()
                    self.assertIn("no review" if rounds == 0 else "rounds: 1 of 1", result)
                    with contextlib.closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
                        row = db.execute("SELECT no_review, rounds_used FROM runs WHERE run_id=?",
                                         (directory.name,)).fetchone()
                        self.assertEqual(row, (1 - rounds, rounds))
                        if rounds == 0:
                            self.assertIn(("landing", 0), db.execute(
                                "SELECT kind, exit FROM checks WHERE run_id=?", (directory.name,)).fetchall())
                    if rounds == 0:
                        self.assertIsNone(state["reviewer"])
                        self.assertIn("retry.txt", rig.files())
                        shown = home.ak("run", "status", directory.name, "--plain")
                        self.assertIn("no review", shown.out)

    def test_a_pr_also_lands_without_a_reviewer_or_a_published_review(self):
        for project, own in ((False, False), (True, False), (True, True)):
            with self.subTest(project=project, own=own):
                home, rig, fakes, done, directory, state = self.launch(0, project=project, pr=True, own=own)
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual((state["verdict"], state["merged"]), ("PASS", True))
                self.assertEqual((fakes["claude"].n, fakes["codex"].n), (0, 0))
                self.assertIn("retry.txt", rig.files())
                self.assertFalse(state["review_posted"])
                self.assertIn("no review", (directory / "result.md").read_text().splitlines())

    def test_done_when_and_rules_still_refuse_delivery(self):
        bad_rules = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "guide.md": "prose\n"}}
        for work, checks in (("work", ("false",)), (bad_rules, ("test -f retry.txt",))):
            with self.subTest(checks=checks):
                _, _, fakes, done, _, state = self.launch(0, work=work, checks=checks)
                self.assertNotEqual(done.code, 0)
                self.assertFalse(state["merged"])
                self.assertEqual(fakes["codex"].n, 0)

    def test_a_red_landing_suite_is_fixed_and_checked_without_review(self):
        bad = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "bad.txt": "bad\n"}}
        fix = {"sh": "git rm -q bad.txt", "commit": "remove bad.txt", "hand_in": [["done"]],
               "final": "## Summary\nremoved bad.txt"}
        for pr in (False, True):
            with self.subTest(pr=pr):
                _, _, fakes, done, _, state = self.launch(
                    0, pr=pr, own=pr, work=fix if pr else [bad, fix], files=bad["write"])
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertTrue(state["merged"])
                self.assertEqual([turn["role"] for turn in fakes["claude"].runs()],
                                 ["fixer"] if pr else ["executor", "fixer"])
                self.assertEqual(fakes["codex"].n, 0)

    def test_unmerged_prs_run_the_suite_without_review(self):
        for own in (False, True):
            for red in (False, True):
                with self.subTest(own=own, red=red):
                    files = {"retry.txt": "hello\n", **({"bad.txt": "bad\n"} if red else {})}
                    _, _, fakes, done, directory, state = self.launch(
                        0, pr=True, own=own, files=files, flags=("--no-merge",))
                    self.assertEqual(done.code, int(red), done.out + done.err)
                    self.assertFalse(state["merged"])
                    self.assertEqual((fakes["claude"].n, fakes["codex"].n), (0, 0))
                    self.assertIn("$ test ! -f bad.txt", (directory / "round-1/donewhen.log").read_text())

    def test_batches_need_only_the_executor_when_review_is_off(self):
        for project in (False, True):
            with self.subTest(project=project):
                home, rig, _, fakes = self.staged(0, project=project)
                fakes["codex"].answer("usage", json.dumps({"meters": [{"name": "weekly", "used": 100}]}))
                tasks = [taskfile.write(home, rig.path if project else "none", title) for title in ("Alpha", "Beta")]
                proc = home.spawn("run", *map(str, tasks), "--no-merge")
                deadline, state = time.monotonic() + 90, {}
                while proc.poll() is None and time.monotonic() < deadline:
                    receipts = list((home.path / ".agentkit/jobs").glob("*/job.json"))
                    state = json.loads(receipts[0].read_text()) if receipts else {}
                    if any(task.get("budget_wait") for task in state.get("tasks", [])):
                        break
                    time.sleep(.05)
                self.assertIsNotNone(proc.poll(), state)
                self.assertEqual(proc.wait(), 0, home.log("spawn-1.err").read_text())
                self.assertEqual((fakes["claude"].n, fakes["codex"].n), (2, 0))

    def test_a_pr_suite_can_regenerate_tracked_files_without_failing_the_run(self):
        home, rig, gh, fakes = self.staged(0)
        suite = "printf regenerated > cache.txt && test -s cache.txt"
        rig.commit({"AGENTS.md": f"---\ntests: {suite}\nhealth: none\n---\n# Widgets\n", "cache.txt": "original\n"})
        rig.branch("contrib", {"retry.txt": "hello\n"})
        done = home.ak("run", "--review-pr", gh.open_pr(rig, "contrib", author="other-dev"),
                       "--no-merge", timeout=90)
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual((done.code, state["verdict"]), (0, "PASS"), done.out + done.err)
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (0, 0))
        self.assertEqual(Path(state["worktree"], "cache.txt").read_text(), "original\n")
        self.assertIn("+regenerated", (directory / "tests-changes.patch").read_text())
        self.assertIn(f"$ {suite}\n[exit 0]", (directory / "round-1/donewhen.log").read_text())


if __name__ == "__main__":
    unittest.main()
