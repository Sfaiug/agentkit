"""A Claude worker turn's tokens are kept by model and type, with the login it ran on.

A turn's last `result` gives its `turn_usage` rows in history.db: one per model its `modelUsage`
names, each count its growth over the session's earlier turn in the run, else one row under no
model holding the result's own `usage`.  Each turn is counted at its end and again at its run's
end, and the second adds nothing.  Black-box: AK_BIN runs tasks through
tests/fixtures/akbin.py on fake harnesses whose events are results in the shape Claude writes
them, and history.db is read with sqlite3.
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
SESSION = "session-acme"
TYPES = ("input", "cache_write", "cache_read", "output")


def result(usage, models=None):
    """A Claude `result` event's line: its own `usage`, and the session's `modelUsage`."""
    event = {"type": "result", "subtype": "success", "session_id": SESSION,
             "usage": dict(zip(("input_tokens", "cache_creation_input_tokens",
                                "cache_read_input_tokens", "output_tokens"), usage))}
    if models is not None:
        event["modelUsage"] = {model: {
            **dict(zip(("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens",
                        "outputTokens"), counts)), "costUSD": 0.5} for model, counts in models.items()}
    return json.dumps({"type": "system", "subtype": "init", "session_id": SESSION}) + "\n" \
        + json.dumps(event) + "\n"


# Round 1's turn and the fix that resumes its session: `modelUsage` totals both turns, its
# subagent's model too, which `usage` leaves out.
FIRST = result((10, 1000, 5000, 200), {"claude-opus-5": (10, 1000, 5000, 200),
                                       "claude-haiku-5": (3, 300, 0, 40)})
SECOND = result((5, 500, 4000, 60), {"claude-opus-5": (15, 1500, 9000, 260),
                                     "claude-haiku-5": (5, 350, 100, 50)})
ALONE = result((7, 70, 700, 17))


def rows(home):
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM turn_usage ORDER BY began, model")]
    finally:
        connection.close()


def sums(home):
    with sqlite3.connect(home.path / ".agentkit/history.db") as connection:
        return connection.execute("SELECT executor_tokens FROM runs").fetchall()


class Run:
    """One run on a fake Claude executor and a Codex reviewer, from outside."""

    @classmethod
    def start(cls, steps, reviews, providers=None):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"], providers=providers)
        fakeadapter.install(cls.home, claude=steps, codex=reviews)
        cls.before = time.time()
        cls.done = cls.home.ak("run", str(taskfile.write(cls.home, rig.path)), "--no-merge",
                               env=OWNERS, timeout=300)
        cls.after = time.time()
        cls.run_dir = taskfile.only_run(cls.home)
        cls.rows = rows(cls.home)

    def test_the_run_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["state"], "pass")

    def turn(self, row):
        """The events its row's turn directory holds; it is one of this run's."""
        turn = Path(row["turn"])
        self.assertEqual(turn.parent.parent.resolve(), self.run_dir.resolve(), row)
        self.assertLessEqual(self.before, row["began"], row)
        self.assertLessEqual(row["began"], row["at"], row)
        self.assertLessEqual(row["at"], self.after, row)
        return (turn / "events.jsonl").read_text()

    def kept(self):
        return [(self.turn(row), row["run_id"], row["role"], row["account"], row["model"],
                 *(row[kind] for kind in TYPES)) for row in self.rows]


class AResumedSession(Run, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a finding round 2's fix answers, so that round's review passes
        finding = {"final": "Found one.", "hand_in": [
            ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
             'test "$(cat retry.txt)" != hello'], ["done"]]}
        fix = {"write": {"retry.txt": "hello again\n"}, "commit": "fix retry.txt",
               "final": "## Summary\nfixed", "hand_in": [["done"]]}
        cls.start([{**fakeadapter.WORK, "session": SESSION, "events": FIRST},
                   {**fix, "session": SESSION, "events": SECOND}], [finding, "pass"],
                  providers={"anthropic": {"mode": "subscription", "accounts": ["second"]}})

    def test_each_model_keeps_its_turn_s_four_counts_and_the_next_turn_only_their_growth(self):
        run = self.run_dir.name
        self.assertEqual(self.kept(), [
            (FIRST, run, "executor", "second", "claude-haiku-5", 3, 300, 0, 40),
            (FIRST, run, "executor", "second", "claude-opus-5", 10, 1000, 5000, 200),
            (SECOND, run, "executor", "second", "claude-haiku-5", 2, 50, 100, 10),
            (SECOND, run, "executor", "second", "claude-opus-5", 5, 500, 4000, 60)])

    def test_the_second_turn_began_after_the_first_ended(self):
        self.assertLessEqual(self.rows[1]["at"], self.rows[2]["began"], self.rows)

    def test_counting_again_at_the_run_s_end_adds_nothing_and_the_sum_stays(self):
        self.assertEqual(len(self.rows), 4, self.rows)
        self.assertEqual(sums(self.home), [(6210 + 4565,)])


class AResultWithoutModelUsage(Run, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start({**fakeadapter.WORK, "events": ALONE}, "pass")

    def test_it_keeps_one_row_under_no_model_with_its_usage_on_the_default_login(self):
        self.assertEqual(self.kept(), [
            (ALONE, self.run_dir.name, "executor", "default", None, 7, 70, 700, 17)])
        self.assertEqual(sums(self.home), [(794,)])


if __name__ == "__main__":
    unittest.main()
