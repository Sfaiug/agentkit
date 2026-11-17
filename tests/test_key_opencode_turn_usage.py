"""An OpenCode worker turn's tokens are kept by type, under the model it was launched with, and
`ak usage --json` prices its login's spend from them.

An OpenCode turn's events end in the `result` line adapters/opencode.sh appends from the
session's export: the session's totals so far, whatever model ran each turn of it, its output
counting the reasoning.  Its `turn_usage` row in history.db holds what each total grew by since
the same session's earlier turn in the run, under the model its entry launched it with, and the
login's `listed_usd` is those rows at their models' listed prices.  Black-box: AK_BIN runs a
task through tests/fixtures/akbin.py on a fake harness configured as `opencode` and a Claude
reviewer, with an invented board in its Home, and history.db is read with sqlite3.
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
SESSION = "ses_acme"
TYPES = ("input", "cache_write", "cache_read", "output")
# each release's prices a million tokens of input, cache write, cache read and output
RELEASES = {"anvil-1": ("Anvil 1", (2, 2.5, 0.2, 10)), "anvil-2": ("Anvil 2", (4, 5, 0.4, 20))}
COLUMNS = ("aa.price1mInputTokens", "aa.cacheWritePrice", "aa.cacheHitPrice",
           "aa.price1mOutputTokens")


def events(input, cache_write, cache_read, output):
    """An `opencode run --format json` turn's answer, then the session's totals so far."""
    return "".join(json.dumps(event) + "\n" for event in (
        {"type": "text", "sessionID": SESSION, "part": {"type": "text", "text": "Done."}},
        {"type": "result", "sessionID": SESSION, "usage": {
            "input_tokens": input, "output_tokens": output,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}}))


FIRST = events(300_000, 100_000, 600_000, 40_000)
SECOND = events(700_000, 150_000, 2_000_000, 100_000)


def board():
    now = time.time()
    rows = [{"model": name, "effort": "high", "maker": "Acme", "deprecated": False,
             "slug": slug, "values": dict(zip(COLUMNS, prices)),
             "release": {"slug": slug, "name": name, "deprecatedTo": None}}
            for slug, (name, prices) in RELEASES.items()]
    return {"artificialanalysis.ai": {"asked_at": now, "fetched_at": now, "error": None,
                                      "build": "", "rows": rows}}


class ASessionResumedUnderAnotherModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.configure("acme/anvil-1")
        cls.home.write(".agentkit/state/boards.json", board())
        # a finding round 1 spends its only round on, which the fix resuming the session answers
        finding = {"final": "Found one.", "hand_in": [
            ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
             'test "$(cat retry.txt)" != hello'], ["done"]]}
        fix = {"write": {"retry.txt": "hello again\n"}, "commit": "fix retry.txt",
               "final": "## Summary\nfixed", "hand_in": [["done"]]}
        cls.fakes = fakeadapter.install(
            cls.home, claude=[finding, "pass"],
            opencode=[{**fakeadapter.WORK, "session": SESSION, "events": FIRST},
                      {**fix, "session": SESSION, "events": SECOND}])
        task = taskfile.write(cls.home, Rig(cls.home, "widgets").path, front={"rounds": 1})
        cls.done = cls.home.ak("run", str(task), "--no-merge", env=OWNERS, timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.failed = json.loads((cls.run_dir / "run.json").read_text())["state"]
        cls.configure("acme/anvil-2")
        cls.resumed = cls.home.ak("run", "resume", cls.run_dir.name, "--rounds", "2",
                                  env=OWNERS, timeout=300)
        connection = sqlite3.connect(cls.home.path / ".agentkit/history.db")
        connection.row_factory = sqlite3.Row
        try:
            cls.rows = [dict(row) for row in
                        connection.execute("SELECT * FROM turn_usage ORDER BY began")]
        finally:
            connection.close()

    @classmethod
    def configure(cls, model):
        akconfig.write(cls.home, {"anvil": {"harness": "opencode", "model": model,
                                            "provider": "acme"}, "opus": {}},
                       workers=["anvil"], reviewers=["opus"],
                       providers={"acme": {"mode": "subscription"}})

    def test_the_run_fails_its_one_round_then_passes_resumed_on_the_same_session(self):
        self.assertEqual(self.failed, "fail", self.done.out + self.done.err)
        self.assertEqual(self.resumed.code, 0, self.resumed.out + self.resumed.err)
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["state"], "pass")
        self.assertEqual([call["argv"][5:] for call in self.fakes["opencode"].runs()],
                         [[], [SESSION]])

    def test_each_turn_keeps_what_the_session_grew_by_under_its_model(self):
        run = self.run_dir.name
        self.assertEqual(
            [((Path(row["turn"]) / "events.jsonl").read_text(), row["run_id"], row["role"],
              row["model"], *(row[kind] for kind in TYPES)) for row in self.rows],
            [(FIRST, run, "executor", "acme/anvil-1", 300_000, 100_000, 600_000, 40_000),
             (SECOND, run, "executor", "acme/anvil-2", 400_000, 50_000, 1_400_000, 60_000)])

    def test_the_login_spent_its_rows_at_their_models_listed_prices(self):
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        # Anvil 1: 0.3M input at $2, 0.1M written at $2.5, 0.6M read at $0.2, 40k output at $10;
        # Anvil 2: 0.4M input at $4, 50k written at $5, 1.4M read at $0.4, 60k output at $20
        self.assertAlmostEqual(json.loads(done.out)["providers"]["acme"]["listed_usd"],
                               (0.6 + 0.25 + 0.12 + 0.4) + (1.6 + 0.25 + 0.56 + 1.2))


if __name__ == "__main__":
    unittest.main()
