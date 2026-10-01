"""Executor and fixer closings reach the real loop through offline adapters."""

import json
import os
import unittest
from unittest.mock import patch

import test_followup_runs as followup
import test_review_gate as gate
from agentkit import run


ADAPTER = r'''import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["GATE_FIXTURE"])
if sys.argv[1] == "usage":
    print('{"meters": [{"name": "weekly", "used": 0}]}')
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available": 0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
wt, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = ("reviewer" if prompt.startswith("You are the reviewer") else
        "fixer" if prompt.startswith("You are the executor, continuing") else "executor")
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "prompt": prompt}) + "\n")
plan = json.loads((root / "closings.json").read_text())
rows = plan[role]
row = rows.pop(0) if len(rows) > 1 else rows[0]
(root / "closings.json").write_text(json.dumps(plan))
if role != "reviewer":
    if row.get("fix"):
        test = wt / "test_empty.py"
        test.write_text("from broken import first\nassert first([]) is None\n")
        before = subprocess.run([sys.executable, str(test)], cwd=wt, capture_output=True)
        assert before.returncode != 0, before
        (out / "before.log").write_bytes(before.stderr)
        (wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        subprocess.run([sys.executable, str(test)], cwd=wt, check=True)
        (out.parents[1] / "regression.sh").write_text("python3 test_empty.py\n")
        subprocess.run(["git", "add", "."], cwd=wt, check=True)
        subprocess.run(["git", "commit", "-qm", "Handle empty input"], cwd=wt, check=True)
    elif row["kind"] == "done":
        (wt / "deliverable").write_text("fixture work\n")
(out / "final.md").write_text(row["text"])
(out / "session_id").write_text("fixture-" + role)
if role != "reviewer":
    args = [row["kind"]] + ([row["why"]] if row["kind"] != "done" else [])
    subprocess.run([sys.executable, os.environ["HAND_IN_BIN"], "hand-in", *args], check=True)
'''


def adapters(fixture):
    fixture.stack.enter_context(patch.dict(os.environ, {
        "HAND_IN_BIN": str(gate.REPO / "bin/ak")}))
    fixture.stack.enter_context(patch.object(run, "transient_wait",
                                           side_effect=AssertionError("unexpected retry")))
    for harness in {entry["harness"] for entry in fixture.cfg["models"].values()}:
        fixture.script(fixture.root / "adapters" / f"{harness}.sh", ADAPTER)


def closing(kind, **kwargs):
    return {"kind": kind, "why": "the task requires an unavailable file",
            "text": "## Summary\nClosed this turn.", **kwargs}


class ExecutorHandsIn(unittest.TestCase):
    script = gate.ReviewGate.script
    launch = gate.ReviewGate.launch

    def setUp(self):
        gate.ReviewGate.setUp(self)
        adapters(self)

    def test_executor_closings_determine_the_run_state_and_why(self):
        for kind, expected in (("done", "pass"), ("blocked", "blocked"),
                               ("not-needed", "not_needed")):
            with self.subTest(kind=kind):
                row = closing(kind, text="## Blocked\nStale text." if kind == "done"
                              else "## Summary\nClosed this turn.")
                (self.root / "closings.json").write_text(json.dumps({
                    "executor": [row], "reviewer": [{"text": gate.PASS}]}))
                code, directory, state = self.launch(rounds=1)
                self.assertEqual((code, state["state"]), (int(kind == "blocked"), expected))
                if kind != "done":
                    self.assertEqual(state["error" if kind == "blocked" else "not_needed"], row["why"])
                    self.assertIn(row["why"], (directory / "result.md").read_text())
                    self.assertEqual(state["round_summaries"], [])
                records = next(directory.glob("round-1/executor/hand-in.jsonl")).read_text()
                self.assertEqual(json.loads(records.splitlines()[-1])["kind"], kind)

    def test_fixer_closings_determine_the_run_state_and_why(self):
        for kind, expected in (("done", "pass"), ("blocked", "blocked"),
                               ("not-needed", "not_needed")):
            with self.subTest(kind=kind):
                row = closing(kind, text="## Blocked\nStale text." if kind == "done"
                              else "## Summary\nClosed this turn.")
                (self.root / "closings.json").write_text(json.dumps({
                    "executor": [closing("done")], "fixer": [row],
                    "reviewer": [{"text": gate.fail(1)}, {"text": gate.PASS}]}))
                code, directory, state = self.launch(rounds=3)
                self.assertEqual((code, state["state"]), (int(kind == "blocked"), expected))
                if kind != "done":
                    self.assertEqual(state["error" if kind == "blocked" else "not_needed"], row["why"])
                    self.assertEqual(len(state["round_summaries"]), 1)
                records = next(directory.glob("round-2/executor/hand-in.jsonl")).read_text()
                self.assertEqual(json.loads(records.splitlines()[-1])["kind"], kind)


class FixRunHandsIn(unittest.TestCase):
    script = followup.FollowupRuns.script
    git = followup.FollowupRuns.git
    spawn = followup.FollowupRuns.spawn
    gh = followup.FollowupRuns.gh
    source = followup.FollowupRuns.source
    start = followup.FollowupRuns.start
    drive = followup.FollowupRuns.drive

    def setUp(self):
        followup.FollowupRuns.setUp(self)
        adapters(self)

    def first_closing(self, kind, expected):
        directory, source = self.source()
        child = self.start(directory, source)[0]
        row = closing(kind, why="target already fixes empty input" if kind == "not-needed"
                      else "Should empty input return None or raise ValueError?", fix=kind == "done")
        (self.root / "closings.json").write_text(json.dumps({
            "executor": [row], "reviewer": [{"text": gate.PASS}]}))
        code, state = self.drive(child)
        self.assertEqual((code, state["state"]), (int(kind == "blocked"), expected))
        if kind == "done":
            self.assertTrue(state["merged"])
            self.assertTrue(state["regression_checked"])
        else:
            self.assertEqual(state["error" if kind == "blocked" else "not_needed"], row["why"])
            self.assertIn(row["why"], self.endings[-1])
            self.assertIsNone(state["pr"])
            self.assertEqual(state["round_summaries"], [])
        records = next(child.glob("round-1/executor/hand-in.jsonl")).read_text()
        self.assertEqual(json.loads(records.splitlines()[-1])["kind"], kind)

    def test_first_fix_turn_hands_in_blocked(self):
        self.first_closing("blocked", "blocked")

    def test_first_fix_turn_hands_in_not_needed(self):
        self.first_closing("not-needed", "not_needed")

    def test_first_fix_turn_hands_in_done(self):
        self.first_closing("done", "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
