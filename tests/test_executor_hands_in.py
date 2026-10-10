"""Executor and fixer closings reach the real loop through offline adapters."""

import json
import os
import unittest
from unittest.mock import patch

import test_followup_runs as followup
import test_review_gate as gate
from agentkit import record, run


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
        (out.parents[1] / "regression/regression.sh").write_text("python3 test_empty.py\n")
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
                               ("not-needed", "pass")):
            with self.subTest(kind=kind):
                row = closing(kind, text="## Blocked\nStale text." if kind == "done"
                              else "## Summary\nClosed this turn.")
                (self.root / "closings.json").write_text(json.dumps({
                    "executor": [row], "fixer": [closing("done")],
                    "reviewer": [{"text": gate.PASS}]}))
                code, directory, state = self.launch(rounds=1)
                self.assertEqual((code, state["state"]), (int(kind == "blocked"), expected))
                if kind == "blocked":
                    self.assertEqual(state["error"], row["why"])
                    self.assertIn(row["why"], (directory / "result.md").read_text())
                    self.assertEqual(state["round_summaries"], [])
                else:
                    self.assertTrue(run.review_pass(state, self.cfg))
                    self.assertEqual(len(state["round_summaries"]), 1)
                records = next(directory.glob("round-1/executor/hand-in.jsonl")).read_text()
                self.assertEqual(json.loads(records.splitlines()[-1])["kind"], kind)

    def test_fixer_closings_determine_the_run_state_and_why(self):
        for kind, expected in (("done", "pass"), ("blocked", "blocked"),
                               ("not-needed", "pass")):
            with self.subTest(kind=kind):
                row = closing(kind, text="## Blocked\nStale text." if kind == "done"
                              else "## Summary\nClosed this turn.")
                (self.root / "closings.json").write_text(json.dumps({
                    "executor": [closing("done")], "fixer": [row],
                    "reviewer": [{"text": gate.fail(1)}, {"text": gate.PASS}]}))
                code, directory, state = self.launch(rounds=3)
                self.assertEqual((code, state["state"]), (int(kind == "blocked"), expected))
                if kind == "blocked":
                    self.assertEqual(state["error"], row["why"])
                    self.assertEqual(len(state["round_summaries"]), 1)
                else:
                    self.assertTrue(run.review_pass(state, self.cfg))
                    self.assertEqual(len(state["round_summaries"]), 2)
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

    def first_closing(self, kind, expected, resume=False, why=None):
        directory, source = self.source()
        child = self.start(directory, source)[0]
        row = closing(kind, why="target already fixes empty input" if kind == "not-needed"
                      else "Should empty input return None or raise ValueError?", fix=kind == "done")
        if why is not None:
            row["why"] = why
        if resume and kind == "done":
            row["text"] = "not needed: stale text"
        (self.root / "closings.json").write_text(json.dumps({
            "executor": [row], "reviewer": [{"text": gate.PASS}]}))
        if resume:
            with patch.object(run, "review_records", side_effect=record.StopRequested("fixture host ended")):
                code, state = self.drive(child)
            self.assertEqual(code, 1)
            code, state = self.drive(child, prior=state)
            calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
            self.assertEqual(sum(call["role"] == "executor" for call in calls), 1)
        else:
            code, state = self.drive(child)
        self.assertEqual((code, state["state"]), (int(kind == "blocked"), expected))
        if kind == "done":
            self.assertTrue(state["merged"])
            self.assertTrue(state["regression_checked"])
        else:
            self.assertEqual(state["error" if kind == "blocked" else "not_needed"], row["why"])
            self.assertIn(" ".join(row["why"].split()), self.endings[-1])
            self.assertNotIn("\n", self.endings[-1])
            self.assertIsNone(state["pr"])
            self.assertEqual(state["round_summaries"], [])
        records = next(child.glob("round-1/executor/hand-in.jsonl")).read_text()
        self.assertEqual(json.loads(records.splitlines()[-1])["kind"], kind)

    def test_first_fix_turn_hands_in_blocked(self):
        self.first_closing("blocked", "blocked")

    def test_first_fix_turn_hands_in_not_needed(self):
        self.first_closing("not-needed", "not_needed")

    def test_not_needed_handback_keeps_a_multiline_why_on_one_line(self):
        self.first_closing("not-needed", "not_needed", why="gone on the target\n\nsee commit abc123")

    def test_first_fix_turn_hands_in_done(self):
        self.first_closing("done", "pass")

    def test_later_fix_turn_not_needed_still_checks_and_reviews(self):
        directory, source = self.source()
        child = self.start(directory, source)[0]
        (self.root / "closings.json").write_text(json.dumps({
            "executor": [closing("done", fix=True)], "fixer": [closing("not-needed")],
            "reviewer": [{"text": gate.fail(1).replace("file.py:1", "broken.py:2")},
                         {"text": gate.PASS}]}))
        code, state = self.drive(child)
        # a later not-needed changes nothing, so ak's replay of round one's finding keeps
        # blocking whatever the reviewer says, each round checked and reviewed until none is left
        self.assertEqual((code, state["state"]), (1, "fail"))
        self.assertFalse(state["merged"])
        self.assertTrue(state["regression_checked"])
        self.assertEqual([row["finding_count"] for row in state["round_summaries"]], [1, 1, 1])
        self.assertNotIn("not_needed", state)

    def test_resume_keeps_the_blocked_closing(self):
        self.first_closing("blocked", "blocked", resume=True)

    def test_resume_keeps_the_not_needed_closing(self):
        self.first_closing("not-needed", "not_needed", resume=True)

    def test_resume_keeps_the_done_closing(self):
        self.first_closing("done", "pass", resume=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
