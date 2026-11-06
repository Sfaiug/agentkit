"""A Codex worker turn's tokens are kept by type, under the model it was launched with.

A Codex turn's last `turn.completed` totals its thread, whatever model ran each turn of it: its
`turn_usage` row in history.db holds what each count grew by since the same thread's earlier
turn in the run, its input less what was cached or written to the cache, under the model its
entry launched it with, or under no model where that is `default`.  Black-box: AK_BIN runs
tasks through tests/fixtures/akbin.py on a fake harness configured as `codex`, whose events are
in the shape `codex exec --json` writes them, and history.db is read with sqlite3.
"""

import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

OWNERS = {"AK_NOTIFY_SINK": None}
THREAD = "thread-acme"
TYPES = ("input", "cache_write", "cache_read", "output")


def events(usage, thread=THREAD):
    """A `codex exec --json` turn's lines: its thread, then the thread's running `usage`."""
    return "".join(json.dumps(event) + "\n" for event in (
        {"type": "thread.started", "thread_id": thread}, {"type": "turn.started"},
        {"type": "turn.completed", "usage": usage}))


# Round 1's turn writes nothing to the cache; the turn resuming its thread, under another model,
# totals both.  Output includes the reasoning.
FIRST = events({"input_tokens": 9000, "cached_input_tokens": 6000, "output_tokens": 300,
                "reasoning_output_tokens": 120})
SECOND = events({"input_tokens": 25000, "cached_input_tokens": 18000,
                 "cache_write_input_tokens": 2000, "output_tokens": 700,
                 "reasoning_output_tokens": 250})
OWN = events({"input_tokens": 4000, "cached_input_tokens": 1000, "output_tokens": 90},
             thread="thread-acme-own")


def rows(home):
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM turn_usage ORDER BY began")]
    finally:
        connection.close()


class Run:
    """A run on a fake Codex executor and a Claude reviewer, from outside."""

    @classmethod
    def start(cls, model, steps, reviews, **front):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.configure(model)
        cls.fakes = fakeadapter.install(cls.home, codex=steps, claude=reviews)
        cls.task = taskfile.write(cls.home, Rig(cls.home, "widgets").path, front=front)
        cls.before = time.time()
        cls.done = cls.home.ak("run", str(cls.task), "--no-merge", env=OWNERS, timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    @classmethod
    def configure(cls, model):
        akconfig.write(cls.home, {"astra": {"model": model}, "opus": {}}, workers=["astra"],
                       reviewers=["opus"],
                       providers={"openai": {"mode": "subscription", "accounts": ["second"]}})

    @classmethod
    def ended(cls):
        cls.after = time.time()
        cls.rows = rows(cls.home)

    def passed(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["state"], "pass")

    def kept(self):
        """Each row's turn's events, run, role, login, model and counts; its turn is one of
        this run's, begun and ended while it ran."""
        kept = []
        for row in self.rows:
            turn = Path(row["turn"])
            self.assertEqual(turn.parent.parent.resolve(), self.run_dir.resolve(), row)
            self.assertLessEqual(self.before, row["began"], row)
            self.assertLessEqual(row["began"], row["at"], row)
            self.assertLessEqual(row["at"], self.after, row)
            kept.append(((turn / "events.jsonl").read_text(), row["run_id"], row["role"],
                         row["account"], row["model"], *(row[kind] for kind in TYPES)))
        return kept


class AThreadResumedUnderAnotherModel(Run, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a finding round 1 spends its only round on, which the fix resuming the thread answers
        finding = {"final": "Found one.", "hand_in": [
            ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
             'test "$(cat retry.txt)" != hello'], ["done"]]}
        fix = {"write": {"retry.txt": "hello again\n"}, "commit": "fix retry.txt",
               "final": "## Summary\nfixed", "hand_in": [["done"]]}
        cls.start("gpt-acme-1", [{**fakeadapter.WORK, "session": THREAD, "events": FIRST},
                                 {**fix, "session": THREAD, "events": SECOND}],
                  [finding, "pass"], rounds=1)
        cls.failed = json.loads((cls.run_dir / "run.json").read_text())["state"]
        cls.configure("gpt-acme-2")
        cls.resumed = cls.home.ak("run", "resume", cls.run_dir.name, "--rounds", "2",
                                  env=OWNERS, timeout=300)
        cls.ended()

    def test_the_run_fails_its_one_round_then_passes_resumed_on_the_same_thread(self):
        self.assertEqual(self.failed, "fail", self.done.out + self.done.err)
        self.passed(self.resumed)
        self.assertEqual([call["argv"][5:] for call in self.fakes["codex"].runs()],
                         [[], [THREAD]])

    def test_each_turn_keeps_its_own_counts_by_type_under_the_model_it_was_launched_with(self):
        run = self.run_dir.name
        self.assertEqual(self.kept(), [
            (FIRST, run, "executor", "second", "gpt-acme-1", 3000, 0, 6000, 300),
            (SECOND, run, "executor", "second", "gpt-acme-2", 2000, 2000, 12000, 400)])


class TheDefaultModel(Run, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start("default", {**fakeadapter.WORK, "events": OWN}, "pass")
        cls.ended()

    def test_it_keeps_its_turn_under_no_model(self):
        self.passed(self.done)
        self.assertEqual(self.kept(), [
            (OWN, self.run_dir.name, "executor", "second", None, 3000, 0, 1000, 90)])


if __name__ == "__main__":
    unittest.main()
