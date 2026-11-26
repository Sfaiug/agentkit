"""A post-launch edit to a seat file never aborts an already-launched run.

Black-box against AK_BIN in a throwaway HOME: a resumed multi-account run keeps working
when its launching seat gains duplicate reviewers or invalid JSON, history still records
its run row, and a queued own-PR review evaluates its size gate from the captured workers
without failing on a corrupt seat file.
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
from fixtures.akseat import PLAN_LINE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class CorruptSeatNeverAbortsLaunchedRun(unittest.TestCase):
    def _resume_multi_account(self, corrupt):
        with Home() as home:
            home.env["AK_NOTIFY_SINK"] = None
            rig = Rig(home)
            akconfig.write(home, {"beta": {"harness": "claude", "provider": "acme"},
                                  "alpha": {"harness": "claude", "provider": "acme"}},
                           orchestrator="alpha", workers=["beta"],
                           providers={"acme": {"accounts": ["first", "second"]}},
                           settings={"review_rounds": 0})
            home.fake("claude", "#!/bin/sh\nexit 0\n")
            fake = fakeadapter.install(home, claude="dead")["claude"]
            seat_path = home.write(".agentkit/state/session-fix-api.json", {
                "orchestrator": "alpha", "workers": ["beta"], "reviewers": [],
                "account": "first", "cwd": str(rig.path), "created": 1})
            home.write(".agentkit/state/plan-fix-api.md", PLAN_LINE + "\n")
            now = time.time()
            reading = lambda used: {"provider": "acme", "resets": 0, "meters": [
                {"name": "weekly_all", "used": used, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
            readings = {"fetched_at": now, "reset_checked_at": now,
                        "providers": {"acme": {**reading(10), "accounts": {
                            "first": reading(10), "second": reading(20)}}}}
            home.write(".agentkit/state/usage.json", readings)
            task = taskfile.write(home, rig.path)

            parked = home.ak("run", str(task), "--no-merge",
                             env={"AGENTKIT_SESSION": "fix-api"}, timeout=300)
            self.assertEqual(parked.code, 1, parked.out + parked.err)
            directory = taskfile.only_run(home)
            state = json.loads((directory / "run.json").read_text())
            self.assertEqual((state["state"], state["launched_session"]), ("exhausted", "fix-api"))

            corrupt(seat_path)
            fake.behave("work")
            home.write(".agentkit/state/usage.json", readings)
            before = len(fake.runs())
            done = home.ak("run", "resume", directory.name, timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            final = json.loads((directory / "run.json").read_text())
            self.assertEqual(final["verdict"], "PASS")
            turns = [call for call in fake.runs()[before:] if call["role"] == "executor"]
            self.assertEqual(len(turns), 1, turns)
            with contextlib.closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
                row = db.execute("SELECT session, orchestrator FROM runs WHERE run_id=?",
                                 (directory.name,)).fetchone()
            return turns[0]["env"].get("AGENTKIT_ACCOUNT"), row

    def test_malformed_reviewers_keep_sparing_the_seats_account_on_resume(self):
        def duplicate_reviewers(seat_path):
            data = json.loads(seat_path.read_text())
            data["reviewers"] = ["beta", "beta"]
            seat_path.write_text(json.dumps(data))

        account, row = self._resume_multi_account(duplicate_reviewers)
        self.assertEqual(account, "second")
        self.assertEqual(row, ("fix-api", "alpha"))

    def test_invalid_json_seat_does_not_abort_resumed_run_or_history(self):
        account, row = self._resume_multi_account(lambda path: path.write_text("invalid JSON"))
        self.assertEqual(account, "first")
        self.assertEqual(row, ("fix-api", "alpha"))

    def test_queued_own_pr_size_gate_uses_captured_workers_over_a_corrupt_seat(self):
        for workers, expected in ((["opus"], "Write it as a task"),
                                  ([], "Split it into smaller PRs.")):
            with self.subTest(workers=workers), Home() as home:
                home.env.update(AK_NOTIFY_SINK=None,
                                AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 16000}))
                akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                               settings={"review_rounds": 3, "orchestrator_lines": 5})
                rules = ("---\ntests: true\nhealth: none\nusers: none\n"
                         "review_rounds: 3\norchestrator_lines: 5\n---\n# Widgets\n")
                rig = Rig(home, "widgets", files={"AGENTS.md": rules})
                rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
                gh = GitHub(home)
                gh.grant(rig.slug, "WRITE")
                fakeadapter.install(home, claude="pass", codex="pass")
                Seat(home, "acme", model="opus", cwd=rig.path, alive=False, planned=True,
                     record={"workers": list(workers), "reviewers": ["astra"]})
                rig.branch("contrib", {"big.txt": "".join(f"line {i}\n" for i in range(20))})
                url = gh.open_pr(rig, "contrib", author="acme")

                # A queued own-PR receipt whose live seat is corrupted before the child runs.
                run_dir = home.path / ".agentkit/runs/queued-own-pr"
                run_dir.mkdir(parents=True)
                (run_dir / "log.txt").touch()
                (run_dir / "run.json").write_text(json.dumps({
                    "run_id": run_dir.name, "state": "queued", "verdict": None,
                    "launched_session": "acme", "launched_orchestrator": "opus",
                    "workers": list(workers), "reviewers": ["astra"],
                    "review_pr": url, "own_pr": True, "own_orchestrator": "opus",
                    "launch_opts": {"--review-pr": url},
                    "policy": {"review_rounds": 3, "orchestrator_lines": 5,
                               "executor_lines": 1000},
                }))
                (home.path / ".agentkit/state/session-acme.json").write_text("invalid JSON")

                done = home.ak("run", "--review-pr", url,
                               env={"AGENTKIT_RUN_DIR": str(run_dir)}, timeout=300)
                self.assertEqual(done.code, 2, done.out + done.err)
                state = json.loads((run_dir / "run.json").read_text())
                self.assertEqual(state["state"], "error", state)
                self.assertIn("too big for the seat", state["error"])
                self.assertIn(expected, state["error"])
                self.assertNotIn("session-acme.json", state["error"])


if __name__ == "__main__":
    unittest.main()
