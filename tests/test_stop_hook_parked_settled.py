"""The stop hook holds a turn only for a run still unsettled, and names commands that work.

A failed run a later merged relaunch `from:` its branch, or a merged continuation of its title,
replaced is settled -- as `ak notify done` and the seat's state read it -- and holds nothing;
a relaunch still running settles nothing yet.  The hold names, per run, only the commands its
state takes: `ak run status <id>` marks an ending looked at, `ak run stop <id>` only where stop
ends it, `ak run resume <id>` only where resume carries it on, with the `--rounds` a FAIL at its
budget needs.  Offline: hooks/orchestrator-stop.sh run as its harness runs it, JSON on stdin,
against fake run records in a throwaway HOME, never a real seat or transcript.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT, ACME = "acme-seat", "/src/acme"
SAID = "Here is my recommendation. Let me know if I should continue."


class ParkedSettled(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".parked-settled-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)
        self.turn = time.time() - 600
        # a done this turn: the stop stands unless a run of the seat's sits parked
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "kind": "done", "text": "Shipped fix-api", "time": self.turn + 1}))

    def run_json(self, name, **fields):
        directory = self.runs / name
        directory.mkdir(exist_ok=True)
        (directory / "run.json").write_text(json.dumps(
            {"run_id": name, "launched_session": SEAT, "repo": ACME,
             "started_at": self.turn - 9000, **fields}) + "\n")

    def worktree(self, name, present=True):
        path = self.home / "wt" / name
        if present:
            path.mkdir(parents=True)
        return str(path)

    def stop(self):
        """One end-of-turn hook call, the first of a fresh turn; what the harness reads back."""
        (self.state / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": self.turn, "blocks": 0}) + "\n")
        transcript = self.home / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": SAID}]}}) + "\n")
        done = subprocess.run(
            ["bash", str(HOOK)], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "fake",
                              "transcript_path": str(transcript)}),
            env={"PATH": os.environ["PATH"], "HOME": str(self.home),
                 "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["reason"] if done.stdout.strip() else ""

    def test_a_run_a_merged_relaunch_or_continuation_replaced_holds_nothing(self):
        for label, later in (
                ("relaunch from its branch", {"from": "ak/fix-api", "title": "fix-api split"}),
                ("continuation of its title", {"title": "fix-api"})):
            with self.subTest(label=label):
                self.setUp()
                self.run_json("fix-api-1", state="fail", recovery_pending=True,
                              title="fix-api", branch="ak/fix-api",
                              worktree=self.worktree("fix-api-1"), finished_at=self.turn - 600)
                self.assertIn("run fix-api-1 parked: ", self.stop())
                # a relaunch still running settles nothing yet
                self.run_json("fix-api-2", state="running", **later)
                self.assertIn("run fix-api-1 parked: ", self.stop())
                self.run_json("fix-api-2", state="pass", merged=True,
                              finished_at=self.turn + 30, **later)
                self.assertEqual(self.stop(), "")

    def test_the_hold_names_per_run_only_the_commands_its_state_takes(self):
        self.run_json("fail-resumed", state="fail", recovery_pending=True, rounds=3,
                      round_summaries=[{}], worktree=self.worktree("fail-resumed"),
                      finished_at=self.turn - 60)
        self.run_json("fail-at-budget", state="fail", recovery_pending=True, rounds=2,
                      round_summaries=[{}, {}], worktree=self.worktree("fail-at-budget"),
                      finished_at=self.turn - 60)
        self.run_json("fail-past-budget", state="fail", recovery_pending=True, rounds=3,
                      round_summaries=[{}, {}, {}], worktree=self.worktree("fail-past-budget"),
                      finished_at=self.turn - 60)
        self.run_json("fail-tree-gone", state="fail", recovery_pending=True, rounds=3,
                      worktree=self.worktree("fail-tree-gone", present=False),
                      finished_at=self.turn - 60)
        self.run_json("error-told", state="error", recovery_pending=True, handed_back=True,
                      error="provider refused", worktree=self.worktree("error-told"),
                      finished_at=self.turn - 60)
        self.run_json("exhausted-spent", state="exhausted",
                      error="three rounds spent: split or re-scope the task",
                      worktree=self.worktree("exhausted-spent"), finished_at=self.turn - 60)
        reason = self.stop()
        for name, ways in (
                ("fail-resumed", ["ak run status fail-resumed", "ak run resume fail-resumed"]),
                ("fail-at-budget", ["ak run status fail-at-budget",
                                    "ak run resume fail-at-budget --rounds 3"]),
                ("fail-past-budget", ["ak run status fail-past-budget"]),
                ("fail-tree-gone", ["ak run status fail-tree-gone"]),
                ("error-told", ["ak run status error-told", "ak run resume error-told",
                                "ak run stop error-told"]),
                ("exhausted-spent", ["ak run resume exhausted-spent",
                                     "ak run stop exhausted-spent"])):
            with self.subTest(run=name):
                self.assertRegex(reason, rf"run {name} parked: .*?\({' / '.join(ways)}\)")
        # `ak run stop` refuses every ending but an error: never offered for a FAIL
        self.assertNotIn("ak run stop fail-", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
