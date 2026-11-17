"""An Antigravity worker turn's tokens are kept by type, and its login's spend priced from them.

Each model call agy finishes streams its own `usage` in its `step_update`: the thinking inside
its output, its cached input beside its input.  The turn's `turn_usage` row in history.db holds
the sum of its calls' input, cache read and output, and no cache write, under the model its
entry launched it with; the closing `result`, which totals the whole conversation, adds
nothing.  `ak usage --json` then prices the login's `listed_usd` from that row.  Black-box:
AK_BIN runs a task through tests/fixtures/akbin.py on a fake harness configured as
`antigravity`, whose events are in the shape `agy --output-format stream-json` writes them, an
invented board in its Home, and history.db is read with sqlite3.
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
TYPES = ("input", "cache_write", "cache_read", "output")
CONVERSATION = "conversation-acme"


def step(index, usage=None):
    """A done step's line: a model call's when it has `usage`, (input, output, thinking, cache
    read), its total the input and output; a tool call's otherwise."""
    update = {"conversation_id": CONVERSATION, "step_index": index, "state": "DONE",
              "step_type": "tool", "tool_name": "run_command"}
    if usage:
        fresh, output, thinking, cached = usage
        update.update(step_type="agent_response", usage={
            "input_tokens": fresh, "output_tokens": output, "thinking_tokens": thinking,
            "cache_read_tokens": cached, "total_tokens": fresh + output})
        del update["tool_name"]
    return {"event": "step_update", "step_update": update}


# Two model calls around a tool call, then the `result` of a conversation that had turns before.
EVENTS = "".join(json.dumps(event) + "\n" for event in (
    {"event": "init", "conversation_id": CONVERSATION, "init": {"model": "nimbus-1"}},
    step(1, (1_000_000, 200_000, 150_000, 4_000_000)), step(2),
    step(3, (500_000, 50_000, 20_000, 6_000_000)),
    {"event": "result", "result": {"conversation_id": CONVERSATION, "status": "SUCCESS",
                                   "usage": {"input_tokens": 4_000_000, "output_tokens": 600_000,
                                             "thinking_tokens": 400_000,
                                             "cache_read_tokens": 25_000_000,
                                             "total_tokens": 4_600_000}}}))
# Nimbus 1's prices a million tokens of input, cache write, cache read and output
PRICES = {"aa.price1mInputTokens": 2, "aa.cacheWritePrice": 2.5, "aa.cacheHitPrice": 0.2,
          "aa.price1mOutputTokens": 10}


def board(now):
    return {"artificialanalysis.ai": {"asked_at": now, "fetched_at": now, "error": None,
                                      "build": "", "rows": [{
        "model": "Nimbus 1", "effort": "high", "maker": "Acme", "deprecated": False,
        "slug": "nimbus-1", "values": PRICES,
        "release": {"slug": "nimbus-1", "name": "Nimbus 1", "deprecatedTo": None}}]}}


class AnAntigravityTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"nimbus": {"harness": "antigravity", "model": "nimbus-1",
                                             "provider": "acme"}, "opus": {}},
                       workers=["nimbus"], reviewers=["opus"],
                       providers={"acme": {"mode": "subscription", "accounts": ["second"]}})
        fakeadapter.install(cls.home, antigravity={**fakeadapter.WORK, "events": EVENTS},
                            claude="pass")
        task = taskfile.write(cls.home, Rig(cls.home, "widgets").path)
        cls.before = time.time()
        cls.done = cls.home.ak("run", str(task), "--no-merge", env=OWNERS, timeout=300)
        cls.after = time.time()
        cls.run_dir = taskfile.only_run(cls.home)
        connection = sqlite3.connect(cls.home.path / ".agentkit/history.db")
        connection.row_factory = sqlite3.Row
        try:
            cls.rows = [dict(row) for row in connection.execute("SELECT * FROM turn_usage")]
        finally:
            connection.close()
        cls.home.write(".agentkit/state/boards.json", board(time.time()))
        cls.usage = cls.home.ak("usage", "--json")

    def test_its_row_holds_its_calls_input_cache_read_and_output_under_its_model(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        [row] = self.rows
        self.assertEqual(Path(row["turn"]).parent.parent.resolve(), self.run_dir.resolve())
        self.assertLessEqual(self.before, row["began"])
        self.assertLessEqual(row["began"], row["at"])
        self.assertLessEqual(row["at"], self.after)
        self.assertEqual((row["run_id"], row["role"], row["account"], row["model"],
                          *(row[kind] for kind in TYPES)),
                         (self.run_dir.name, "executor", "second", "nimbus-1",
                          1_500_000, 0, 10_000_000, 250_000))

    def test_its_logins_spend_is_priced_from_it(self):
        self.assertEqual(self.usage.code, 0, self.usage.out + self.usage.err)
        login = json.loads(self.usage.out)["providers"]["acme"]["accounts"]["second"]
        self.assertAlmostEqual(login["listed_usd"], 1.5 * 2 + 10 * 0.2 + 0.25 * 10)


if __name__ == "__main__":
    unittest.main()
